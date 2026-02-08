import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
import math
from datetime import datetime

# ==========================================
# 1. 데이터 베이스 & 상수 설정
# ==========================================
PRODUCTS = {
    "9in1 모듈 쉘프": {
        "cost_mfg": 60000,       # 제조원가 (KRW)
        "weight_kg": 6.0,
        "dims_cm": [30, 30, 30], # 가로, 세로, 높이
        "cbm_original": 0.027,
    },
    "베를린 테이블": {
        "cost_mfg": 135000,
        "weight_kg": 19.0,
        "dims_cm": [50, 50, 50],
        "cbm_original": 0.125,
    }
}

# 도착지별 설정 (확장 가능하게 구조화)
DESTINATIONS = {
    "Hong Kong": {
        "duty_rate": 0.0,
        "local_handling": 200000,
        "inland_delivery": 300000,
        "currency": "HKD"
    },
    "Japan": {
        "duty_rate": 0.0,  # 품목에 따라 다름, 가구류 기준
        "local_handling": 250000,
        "inland_delivery": 350000,
        "currency": "JPY"
    },
    "USA (West Coast)": {
        "duty_rate": 0.0,  # 가구류 대부분 무관세
        "local_handling": 400000,
        "inland_delivery": 500000,
        "currency": "USD"
    },
    "Singapore": {
        "duty_rate": 0.0,
        "local_handling": 180000,
        "inland_delivery": 250000,
        "currency": "SGD"
    }
}

# FCL 컨테이너 스펙
CONTAINER_SPECS = {
    "20ft": {"max_cbm": 28, "max_kg": 21000},
    "40ft": {"max_cbm": 58, "max_kg": 26000},
    "40ft_HC": {"max_cbm": 68, "max_kg": 26000}
}

# ==========================================
# 2. 유틸리티 함수 (API 및 계산)
# ==========================================

@st.cache_data(ttl=3600)  # 1시간 캐싱
def get_exchange_rate(base_currency="USD"):
    """
    실시간 환율 조회 (KRW 기준)
    - 개선: 캐싱 적용, 정확한 티커 사용, 상세 에러 처리
    """
    ticker_map = {
        "USD": "USDKRW=X",
        "HKD": "HKDKRW=X", 
        "JPY": "JPYKRW=X",
        "SGD": "SGDKRW=X",
        "EUR": "EURKRW=X"
    }
    
    fallback_rates = {
        "USD": 1380,
        "HKD": 177,
        "JPY": 9.2,
        "SGD": 1030,
        "EUR": 1500
    }
    
    if base_currency not in ticker_map:
        return fallback_rates.get(base_currency, 1000)
    
    try:
        ticker = ticker_map[base_currency]
        data = yf.Ticker(ticker).history(period="5d")  # 5일치 조회 (휴일 대비)
        
        if data.empty or 'Close' not in data.columns:
            st.warning(f"⚠️ {base_currency} 환율 데이터 없음. 기본값 사용.")
            return fallback_rates[base_currency]
            
        rate = data['Close'].dropna().iloc[-1]
        return round(float(rate), 2)
        
    except Exception as e:
        st.warning(f"⚠️ 환율 API 오류 ({base_currency}): {str(e)[:50]}... 기본값 사용.")
        return fallback_rates.get(base_currency, 1000)


def validate_inputs(qty: int, product_info: dict) -> tuple[bool, str]:
    """입력값 검증"""
    if qty <= 0:
        return False, "수량은 1 이상이어야 합니다."
    if qty > 10000:
        return False, "수량이 너무 큽니다. (최대 10,000개)"
    if product_info['weight_kg'] <= 0:
        return False, "제품 무게가 유효하지 않습니다."
    return True, "OK"


def calculate_logistics_specs(qty: int, product_info: dict, packing_type: str) -> dict:
    """
    물류 스펙 계산 (개선: 딕셔너리 반환으로 가독성 향상)
    """
    is_module = "모듈" in packing_type or "A안" in packing_type
    vol_factor = 0.7 if is_module else 1.0
    
    # 단위 및 총 부피/중량
    unit_cbm = product_info['cbm_original'] * vol_factor
    total_cbm = unit_cbm * qty
    total_gw = product_info['weight_kg'] * qty
    
    # LCL 청구 CBM (최소 1 CBM)
    billing_cbm = max(1.0, total_cbm)
    
    # 항공 Chargeable Weight 계산
    # 부피무게: (가로x세로x높이) / 6000 per unit, then * qty
    dims = product_info['dims_cm']
    # 모듈 포장 시 치수도 비례 축소 (3차원이므로 vol_factor^(1/3) 적용)
    dim_factor = vol_factor ** (1/3) if is_module else 1.0
    adjusted_dims = [d * dim_factor for d in dims]
    
    vol_weight_per_unit = (adjusted_dims[0] * adjusted_dims[1] * adjusted_dims[2]) / 6000
    vol_weight_total = vol_weight_per_unit * qty
    air_cw = max(total_gw, vol_weight_total)
    
    return {
        "total_cbm": round(total_cbm, 3),
        "billing_cbm": round(billing_cbm, 2),
        "total_gw": round(total_gw, 1),
        "air_cw": round(air_cw, 1),
        "is_module": is_module,
        "vol_factor": vol_factor,
        "adjusted_dims": [round(d, 1) for d in adjusted_dims]
    }


def calculate_fcl_recommendation(total_cbm: float, total_gw: float) -> dict:
    """
    FCL 컨테이너 추천 로직 (개선: CBM 임계점 기반)
    """
    result = {
        "recommend_fcl": False,
        "container_type": None,
        "container_qty": 0,
        "reason": ""
    }
    
    # LCL vs FCL 임계점: 일반적으로 15 CBM 이상이면 FCL 검토
    FCL_THRESHOLD_CBM = 15
    
    if total_cbm < FCL_THRESHOLD_CBM:
        result["reason"] = f"물량({total_cbm:.1f} CBM)이 FCL 임계점({FCL_THRESHOLD_CBM} CBM) 미만"
        return result
    
    # 중량 제한 체크 포함
    if total_cbm <= 28 and total_gw <= 21000:
        result.update({
            "recommend_fcl": True,
            "container_type": "20ft",
            "container_qty": 1,
            "reason": "20ft 1개로 적재 가능"
        })
    elif total_cbm <= 58 and total_gw <= 26000:
        result.update({
            "recommend_fcl": True,
            "container_type": "40ft",
            "container_qty": 1,
            "reason": "40ft 1개로 적재 가능"
        })
    elif total_cbm <= 68 and total_gw <= 26000:
        result.update({
            "recommend_fcl": True,
            "container_type": "40ft_HC",
            "container_qty": 1,
            "reason": "40ft High Cube 1개로 적재 가능"
        })
    else:
        # 복수 컨테이너 필요
        qty_40hc = math.ceil(total_cbm / 68)
        result.update({
            "recommend_fcl": True,
            "container_type": "40ft_HC",
            "container_qty": qty_40hc,
            "reason": f"40ft HC {qty_40hc}개 필요 (대량 물량)"
        })
    
    return result


def calculate_all_shipping_costs(
    logistics_specs: dict,
    kcci_index: float,
    fcl_recommendation: dict
) -> dict:
    """
    모든 운송 모드별 비용 계산 (개선: 구조화된 반환)
    """
    billing_cbm = logistics_specs["billing_cbm"]
    total_cbm = logistics_specs["total_cbm"]
    total_gw = logistics_specs["total_gw"]
    air_cw = logistics_specs["air_cw"]
    
    # === 기본 요율 (KCCI 반영) ===
    rate_ocean_lcl = 15000 * kcci_index      # CBM당
    rate_ocean_20ft = 500000 * kcci_index    # 컨테이너당
    rate_ocean_40ft = 900000 * kcci_index
    rate_ocean_40hc = 950000 * kcci_index
    rate_air_kg = 3500 * kcci_index          # kg당
    
    # === 로컬 비용 ===
    cost_cfs_lcl = 25000 * billing_cbm       # LCL 창고료
    cost_doc = 50000                          # 서류비
    cost_local_fcl_20 = 280000
    cost_local_fcl_40 = 350000
    cost_local_fcl_40hc = 380000
    
    # === 내륙 운송비 (중량 기반) ===
    if total_gw < 1000:
        cost_truck = 350000
    elif total_gw < 2500:
        cost_truck = 450000
    elif total_gw < 5000:
        cost_truck = 600000
    else:
        cost_truck = 700000  # 트레일러급
    
    cost_truck_fcl = 700000  # FCL 전용 트레일러
    
    # === 운송 모드별 총비용 ===
    
    # 1. Ocean LCL
    ocean_freight_lcl = rate_ocean_lcl * billing_cbm
    total_lcl = ocean_freight_lcl + cost_cfs_lcl + cost_truck + cost_doc
    
    # 2. Ocean FCL (조건부 계산)
    fcl_costs = {}
    if fcl_recommendation["recommend_fcl"]:
        ctype = fcl_recommendation["container_type"]
        cqty = fcl_recommendation["container_qty"]
        
        if ctype == "20ft":
            fcl_costs["20ft"] = (rate_ocean_20ft + cost_local_fcl_20 + cost_truck_fcl) * cqty
        elif ctype == "40ft":
            fcl_costs["40ft"] = (rate_ocean_40ft + cost_local_fcl_40 + cost_truck_fcl) * cqty
        elif ctype == "40ft_HC":
            fcl_costs["40ft_HC"] = (rate_ocean_40hc + cost_local_fcl_40hc + cost_truck_fcl) * cqty
    else:
        # FCL 비추천이어도 참고용으로 계산
        fcl_costs["20ft"] = rate_ocean_20ft + cost_local_fcl_20 + cost_truck_fcl
        fcl_costs["40ft"] = rate_ocean_40ft + cost_local_fcl_40 + cost_truck_fcl
    
    # 3. Air Freight
    air_freight = rate_air_kg * air_cw
    total_air = air_freight + cost_truck + cost_doc + 100000  # 항공 핸들링 추가
    
    # === 최적 옵션 결정 ===
    all_options = {"LCL": total_lcl, **{f"FCL_{k}": v for k, v in fcl_costs.items()}}
    best_ocean = min(all_options.items(), key=lambda x: x[1])
    
    return {
        "lcl": {
            "total": total_lcl,
            "freight": ocean_freight_lcl,
            "cfs": cost_cfs_lcl,
            "truck": cost_truck,
            "doc": cost_doc
        },
        "fcl": fcl_costs,
        "air": {
            "total": total_air,
            "freight": air_freight,
            "truck": cost_truck,
            "doc": cost_doc
        },
        "best_ocean": {
            "mode": best_ocean[0],
            "cost": best_ocean[1]
        },
        "rates": {
            "lcl_per_cbm": rate_ocean_lcl,
            "air_per_kg": rate_air_kg
        }
    }


# ==========================================
# 3. 메인 앱 UI
# ==========================================
def main():
    st.set_page_config(layout="wide", page_title="Buntkaki Master v6.1 (Improved)")
    
    st.title("🌏 Buntkaki Export Master v6.1")
    st.caption("✨ 개선 버전: API 안정성 강화, FCL 임계점 로직, 입력값 검증 추가")

    # ==========================================
    # [사이드바] 설정
    # ==========================================
    st.sidebar.header("🔧 설정 (Settings)")
    
    # 1. 환율 (캐싱 적용됨)
    with st.sidebar.expander("💱 실시간 환율", expanded=True):
        col1, col2 = st.columns(2)
        usd_rate = col1.number_input("USD/KRW", value=get_exchange_rate("USD"), min_value=100.0)
        hkd_rate = col2.number_input("HKD/KRW", value=get_exchange_rate("HKD"), min_value=10.0)
        st.caption(f"🕐 조회 시간: {datetime.now().strftime('%H:%M')}")
        
    # 2. 물류 지수 (KCCI)
    kcci_index = st.sidebar.slider(
        "📊 KCCI 물류 지수", 
        0.8, 1.5, 1.05, 
        help="1.00 = 평시, 1.05 = 5% 상승, 1.20 = 20% 상승 (유가/성수기 반영)"
    )

    # 3. 제품 및 조건
    st.sidebar.markdown("---")
    product_sel = st.sidebar.selectbox("📦 제품 선택", list(PRODUCTS.keys()))
    qty = st.sidebar.number_input("📦 주문 수량", value=200, min_value=1, max_value=10000, step=50)
    packing_type = st.sidebar.radio(
        "🎁 포장 방식", 
        ["B안: 완제품 (부피 100%)", "A안: 모듈 상태 (부피 70%)"],
        help="모듈 포장 시 조립이 필요하지만 물류비 절감 가능"
    )
    incoterms = st.sidebar.selectbox(
        "📑 인코텀즈", 
        ["EXW", "FOB", "CFR", "CIF", "DDP"],
        index=1,  # FOB 기본값
        help="EXW(공장도) → FOB(본선인도) → CIF(운임보험포함) → DDP(관세포함)"
    )
    target_market = st.sidebar.selectbox("📍 도착지", list(DESTINATIONS.keys()))

    # ==========================================
    # 입력값 검증
    # ==========================================
    prod = PRODUCTS[product_sel]
    is_valid, error_msg = validate_inputs(qty, prod)
    
    if not is_valid:
        st.error(f"❌ 입력 오류: {error_msg}")
        st.stop()

    # ==========================================
    # 핵심 계산
    # ==========================================
    logistics = calculate_logistics_specs(qty, prod, packing_type)
    fcl_rec = calculate_fcl_recommendation(logistics["total_cbm"], logistics["total_gw"])
    shipping = calculate_all_shipping_costs(logistics, kcci_index, fcl_rec)
    dest_info = DESTINATIONS[target_market]

    # 비용 항목 계산
    cost_mfg_total = prod['cost_mfg'] * qty
    cost_packing_mat = 1500 * qty
    cost_customs_kr = 50000
    best_ocean_cost = shipping["best_ocean"]["cost"]
    cost_insurance = best_ocean_cost * 0.002
    
    is_lcl_winner = shipping["best_ocean"]["mode"] == "LCL"
    cost_truck = shipping["lcl"]["truck"] if is_lcl_winner else 700000
    cost_origin_local = shipping["lcl"]["cfs"] if is_lcl_winner else 280000
    cost_ocean_freight = shipping["lcl"]["freight"] if is_lcl_winner else list(shipping["fcl"].values())[0] if shipping["fcl"] else 0

    # 도착지 비용
    cost_local_dest = dest_info["local_handling"]
    cost_duty = (cost_mfg_total + best_ocean_cost) * dest_info["duty_rate"]
    cost_inland_dest = dest_info["inland_delivery"]

    # ==========================================
    # 탭 구성
    # ==========================================
    tab1, tab2, tab3, tab4 = st.tabs([
        "🚛 물류 루트 비교", 
        "💰 인코텀즈 견적서", 
        "🎯 역산 시뮬레이터", 
        "🗣️ 바이어 설득"
    ])

    # === TAB 1: 물류 루트 비교 ===
    with tab1:
        st.subheader("📦 운송 모드별 비용 비교")
        
        # 주요 지표
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("실제 부피", f"{logistics['total_cbm']:.2f} CBM")
        col2.metric("청구 부피", f"{logistics['billing_cbm']:.2f} CBM", 
                   "최소 1 CBM" if logistics['total_cbm'] < 1 else None)
        col3.metric("총 중량", f"{logistics['total_gw']:,.0f} kg")
        col4.metric("항공 청구중량", f"{logistics['air_cw']:,.0f} kg", "CW 기준")

        # FCL 추천 여부
        if fcl_rec["recommend_fcl"]:
            st.success(f"📦 **FCL 추천**: {fcl_rec['container_type']} × {fcl_rec['container_qty']}개 ({fcl_rec['reason']})")
        else:
            st.info(f"📦 **LCL 추천**: {fcl_rec['reason']}")

        # 비용 비교 차트
        chart_data = [
            {"Mode": "Ocean LCL", "Cost": shipping["lcl"]["total"], "Type": "해상"},
        ]
        for ctype, cost in shipping["fcl"].items():
            chart_data.append({"Mode": f"Ocean FCL ({ctype})", "Cost": cost, "Type": "해상"})
        chart_data.append({"Mode": "Air Freight", "Cost": shipping["air"]["total"], "Type": "항공"})
        
        df_chart = pd.DataFrame(chart_data)
        
        colors = ['#1f77b4' if t == "해상" else '#d62728' for t in df_chart["Type"]]
        fig = px.bar(
            df_chart, x="Mode", y="Cost", 
            text=df_chart["Cost"].apply(lambda x: f"₩{x:,.0f}"),
            title="운송 모드별 총 비용 (트럭/창고료/서류비 포함)"
        )
        fig.update_traces(marker_color=colors)
        fig.update_layout(yaxis_title="비용 (KRW)", xaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

        # 상세 비용 breakdown
        with st.expander("📋 LCL 비용 상세"):
            st.write(f"- 해상운임: ₩{shipping['lcl']['freight']:,.0f} ({shipping['rates']['lcl_per_cbm']:,.0f}/CBM × {logistics['billing_cbm']:.1f})")
            st.write(f"- 창고료(CFS): ₩{shipping['lcl']['cfs']:,.0f}")
            st.write(f"- 내륙운송: ₩{shipping['lcl']['truck']:,.0f}")
            st.write(f"- 서류비: ₩{shipping['lcl']['doc']:,.0f}")
            st.write(f"- **합계: ₩{shipping['lcl']['total']:,.0f}**")

    # === TAB 2: 인코텀즈 견적 ===
    with tab2:
        st.subheader(f"📑 {incoterms} 조건 상세 견적")
        
        items = {
            "1. 제조원가": cost_mfg_total,
            "2. 포장자재비": cost_packing_mat,
            "3. 국내운송(Truck)": cost_truck,
            "4. 수출통관/서류": cost_customs_kr + shipping["lcl"]["doc"],
            "5. 항만/창고료(Origin)": cost_origin_local,
            "6. 국제운송(Ocean)": cost_ocean_freight,
            "7. 적하보험(Insurance)": cost_insurance,
            "8. 도착지 항만료": cost_local_dest,
            "9. 관세(Duty)": cost_duty,
            "10. 도착지 운송": cost_inland_dest
        }

        rules = {
            "EXW": [1, 2],
            "FOB": [1, 2, 3, 4, 5],
            "CFR": [1, 2, 3, 4, 5, 6],
            "CIF": [1, 2, 3, 4, 5, 6, 7],
            "DDP": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        }

        seller_pay = 0
        buyer_pay = 0
        table_data = []

        for idx, (k, v) in enumerate(items.items(), 1):
            is_seller = idx in rules[incoterms]
            payer = "🔴 판매자" if is_seller else "🔵 바이어"
            if is_seller:
                seller_pay += v
            else:
                buyer_pay += v
            table_data.append({
                "항목": k, 
                "금액 (KRW)": f"₩{v:,.0f}", 
                "금액 (USD)": f"${v/usd_rate:,.2f}",
                "부담 주체": payer
            })

        c1, c2, c3 = st.columns(3)
        c1.metric(f"📤 {incoterms} 견적가", f"₩{seller_pay:,.0f}")
        c2.metric("USD 환산", f"${seller_pay/usd_rate:,.2f}")
        c3.metric("📥 바이어 Landed Cost", f"₩{seller_pay+buyer_pay:,.0f}")
        
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)
        
        # 단가 계산
        st.markdown("---")
        unit_price_krw = seller_pay / qty
        unit_price_usd = unit_price_krw / usd_rate
        st.metric(f"📦 {incoterms} 단가", f"${unit_price_usd:.2f} / 개", f"₩{unit_price_krw:,.0f}")

    # === TAB 3: 역산 시뮬레이터 ===
    with tab3:
        st.subheader("🎯 Target Price 역산 시뮬레이터")
        
        col1, col2 = st.columns(2)
        target_usd = col1.number_input("바이어 희망 단가 (USD)", value=85.0, min_value=1.0, step=5.0)
        target_margin = col2.slider("목표 영업이익률 (%)", 10, 50, 25)
        
        # 현재 비용 구조
        total_cost_unit = seller_pay / qty
        target_krw = target_usd * usd_rate
        
        actual_margin_won = target_krw - total_cost_unit
        actual_margin_rate = (actual_margin_won / target_krw) * 100 if target_krw > 0 else 0
        
        # 역산: 목표 마진 달성을 위한 최소 판매가
        min_price_for_target = total_cost_unit / (1 - target_margin/100)
        min_price_usd = min_price_for_target / usd_rate
        
        col1, col2, col3 = st.columns(3)
        col1.metric("현재 원가 (단위당)", f"₩{total_cost_unit:,.0f}", f"${total_cost_unit/usd_rate:.2f}")
        col2.metric("예상 영업이익률", f"{actual_margin_rate:.1f}%", 
                   f"{'✅ 달성' if actual_margin_rate >= target_margin else '❌ 미달'}")
        col3.metric(f"목표 마진({target_margin}%) 달성 최소가", f"${min_price_usd:.2f}")
        
        # 상태 표시
        if actual_margin_rate < 15:
            st.error("⚠️ 이익률 15% 미만! 즉시 비용 절감 또는 단가 재협상이 필요합니다.")
            
            # AI 제안
            suggestions = []
            if not logistics["is_module"]:
                suggestions.append("💡 'A안(모듈)' 포장으로 변경 시 CBM 30% 절감 가능")
            if qty < 500:
                suggestions.append("💡 MOQ를 500개 이상으로 늘리면 단위당 물류비 절감")
            if kcci_index > 1.1:
                suggestions.append("💡 물류 지수가 높습니다. 비수기(1-2월) 선적 검토")
            
            if suggestions:
                st.info("\n".join(suggestions))
                
        elif actual_margin_rate < target_margin:
            st.warning(f"⚠️ 목표 마진({target_margin}%)에 {target_margin - actual_margin_rate:.1f}%p 부족")
        else:
            st.success(f"✅ 거래 가능! 목표 마진 초과 달성 (+{actual_margin_rate - target_margin:.1f}%p)")

        # 손익분기점 분석
        st.markdown("---")
        st.subheader("📊 손익분기점 분석")
        
        fixed_costs = cost_customs_kr + shipping["lcl"]["doc"]  # 고정비
        variable_cost_per_unit = (seller_pay - fixed_costs) / qty  # 변동비
        
        if target_krw > variable_cost_per_unit:
            bep_qty = math.ceil(fixed_costs / (target_krw - variable_cost_per_unit))
            st.metric("손익분기 수량", f"{bep_qty:,}개", 
                     f"현재 {qty}개 → {'이익 구간' if qty >= bep_qty else '손실 구간'}")
        else:
            st.error("❌ 단가가 변동비보다 낮아 손익분기점이 존재하지 않습니다.")

    # === TAB 4: 바이어 설득 ===
    with tab4:
        st.subheader("🗣️ 포장 방식 비교 & 제안서")
        
        # A안/B안 비교
        specs_A = calculate_logistics_specs(qty, prod, "A안: 모듈")
        specs_B = calculate_logistics_specs(qty, prod, "B안: 완제품")
        
        shipping_A = calculate_all_shipping_costs(
            specs_A, kcci_index, 
            calculate_fcl_recommendation(specs_A["total_cbm"], specs_A["total_gw"])
        )
        shipping_B = calculate_all_shipping_costs(
            specs_B, kcci_index,
            calculate_fcl_recommendation(specs_B["total_cbm"], specs_B["total_gw"])
        )
        
        cost_A = shipping_A["lcl"]["total"]
        cost_B = shipping_B["lcl"]["total"]
        savings = cost_B - cost_A
        savings_usd = savings / usd_rate
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### 📦 B안: 완제품")
            st.write(f"- 부피: {specs_B['total_cbm']:.2f} CBM")
            st.write(f"- 물류비: ₩{cost_B:,.0f}")
            st.write("- 장점: 바로 판매 가능")
            st.write("- 단점: 높은 물류비")
            
        with col2:
            st.markdown("### 📦 A안: 모듈 포장")
            st.write(f"- 부피: {specs_A['total_cbm']:.2f} CBM")
            st.write(f"- 물류비: ₩{cost_A:,.0f}")
            st.write("- 장점: 물류비 절감")
            st.write("- 단점: 현지 조립 필요")
        
        if savings > 0:
            st.success(f"💰 **A안 선택 시 절감액: ₩{savings:,.0f} (${savings_usd:,.2f})**")
        else:
            st.info("현재 조건에서는 완제품 배송이 유리합니다.")

        # 이메일 템플릿
        st.markdown("---")
        email_template = f"""Subject: Logistics Cost Optimization Proposal - {product_sel}

Dear Valued Partner,

Following our analysis of your order ({qty} units of {product_sel}), we would like to present a cost-saving opportunity.

**Current Shipping Volume Comparison:**
- Option A (Module Packing): {specs_A['total_cbm']:.2f} CBM
- Option B (Assembled): {specs_B['total_cbm']:.2f} CBM

**Estimated Savings with Option A:**
- Logistics Cost Reduction: ${savings_usd:,.2f} ({(savings/cost_B*100):.1f}%)
- This includes: Ocean Freight + CFS Warehouse Charges

**Trade-off Consideration:**
Option A requires local assembly (approx. 15-20 min per unit).
We can provide detailed assembly instructions and video guides.

**Our Recommendation:**
{"We strongly recommend Option A for maximum margin optimization." if savings > 100000 else "Both options are viable. Please choose based on your operational capacity."}

Please let us know your preference, and we'll proceed with the shipment arrangement.

Best regards,
Buntkaki Export Team

---
Quote valid for: 14 days
Incoterms: {incoterms}
Destination: {target_market}
Exchange Rate Applied: ${usd_rate:,.2f}/USD
"""
        
        st.text_area("📩 제안 이메일 템플릿", email_template, height=400)
        
        if st.button("📋 클립보드에 복사"):
            st.write("이메일 내용이 준비되었습니다. 위 텍스트를 선택하여 복사해주세요.")


if __name__ == "__main__":
    main()
