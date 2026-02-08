import streamlit as st
import pandas as pd
import plotly.express as px
import yfinance as yf
import requests
import math

# ==========================================
# 1. 데이터 베이스 (분트카키 설정)
# ==========================================
PRODUCTS = {
    "9in1 모듈 쉘프": {
        "price_retail_krw": 199000,
        "cost_mfg": 60000,
        "weight_kg": 6.0,
        "dims_cm": [30, 30, 30],  # 가로, 세로, 높이
        "hs_code": "9403.70"
    },
    "베를린 테이블": {
        "price_retail_krw": 450000,
        "cost_mfg": 135000,
        "weight_kg": 19.0,
        "dims_cm": [50, 50, 50],
        "hs_code": "9403.60"
    }
}

# ==========================================
# 2. 유틸리티 함수 (API 및 계산)
# ==========================================

# 2-1. 환율 API 연동 (Yahoo Finance)
def get_exchange_rate(target="USD"):
    try:
        # Yahoo Finance 티커: 원달러=KRW=X (역수 계산 필요), 원홍콩=HKDKRW=X
        if target == "USD":
            ticker = "KRW=X"
            data = yf.Ticker(ticker).history(period="1d")
            rate = data['Close'].iloc[-1] # 1달러당 원화 (예: 1300)
        elif target == "HKD":
            ticker = "HKDKRW=X"
            data = yf.Ticker(ticker).history(period="1d")
            rate = data['Close'].iloc[-1] # 1홍콩달러당 원화 (예: 170)
        return round(rate, 2)
    except Exception as e:
        st.sidebar.error(f"환율 API 연동 실패: {e}")
        return 1300 if target == "USD" else 170 # 기본값

# 2-2. KCCI 물류비 API 연동 (가상 구현)
def get_kcci_logistics_index():
    """
    KCCI(대한상공회의소)나 관련 물류 API를 호출하여 변동 지수를 가져옵니다.
    실제 API URL과 Key가 있다면 아래 주석을 해제하고 사용하세요.
    """
    try:
        # url = "https://api.kcci.or.kr/logistics/index?apikey=YOUR_KEY"
        # response = requests.get(url)
        # index = response.json()['current_index']
        # return index
        return 1.05  # 예: 평시 대비 5% 인상된 상태라고 가정
    except:
        return 1.0

# 2-3. CBM 및 운임 중량 계산
def calculate_logistics_specs(qty, dims_cm, weight_kg, packing_type):
    # 포장 조건에 따른 부피 감소 (모듈 상태: 30% 절감 가정)
    vol_factor = 0.7 if packing_type == "모듈 상태 (부피 절감)" else 1.0
    
    # 1개당 CBM (Cubic Meter)
    cbm_per_unit = (dims_cm[0] * dims_cm[1] * dims_cm[2]) / 1_000_000 * vol_factor
    total_cbm = cbm_per_unit * qty
    total_gross_weight = weight_kg * qty

    # 해상 운임 중량 (R/T): 1 CBM = 1 Ton (1000kg)
    ocean_revenue_ton = max(total_cbm, total_gross_weight / 1000)

    # 항공 운임 중량 (Chargeable Weight): 1 CBM = 167kg (혹은 6000으로 나눔)
    air_volumetric_weight = (dims_cm[0] * dims_cm[1] * dims_cm[2] * qty * vol_factor) / 6000
    air_chargeable_weight = max(total_gross_weight, air_volumetric_weight)

    return total_cbm, total_gross_weight, ocean_revenue_ton, air_chargeable_weight

# ==========================================
# 3. 메인 앱 UI
# ==========================================
def main():
    st.set_page_config(layout="wide", page_title="Buntkaki Global Export Simulator v2.0")
    
    st.title("🌏 Buntkaki Export Simulator v2.0")
    st.markdown("API 기반 실시간 환율 & 최적 물류 루트 산출 시스템")

    # [사이드바] 기본 설정
    st.sidebar.header("1. 기본 설정")
    
    # 환율 설정
    use_manual_rate = st.sidebar.checkbox("고시 환율 수동 입력", value=False)
    
    if use_manual_rate:
        usd_rate = st.sidebar.number_input("원/달러 고시 환율", value=1350)
        hkd_rate = st.sidebar.number_input("원/홍콩달러 고시 환율", value=175)
    else:
        with st.sidebar.spinner("환율 정보를 가져오는 중..."):
            usd_rate = get_exchange_rate("USD")
            hkd_rate = get_exchange_rate("HKD")
        st.sidebar.success(f"API 연동 완료: USD {usd_rate} / HKD {hkd_rate}")

    kcci_index = get_kcci_logistics_index()
    st.sidebar.info(f"📊 KCCI 물류비 변동 지수 적용: {kcci_index}x")

    # 제품 설정
    product_sel = st.sidebar.selectbox("수출 제품", list(PRODUCTS.keys()))
    qty = st.sidebar.number_input("수량 (PCS)", value=500, step=50)
    packing_type = st.sidebar.radio("포장 방식", ["모듈 상태 (부피 절감)", "완제품 (박스 포장)"])
    incoterms = st.sidebar.selectbox("인코텀즈 조건", ["EXW", "FOB", "CFR", "CIF", "DDP"])
    
    target_market = st.sidebar.selectbox("도착 국가", ["Hong Kong", "Japan", "USA"])

    # ---------------------------------------------------------
    # 로직 계산
    # ---------------------------------------------------------
    prod = PRODUCTS[product_sel]
    total_cbm, total_gw, ocean_rt, air_cw = calculate_logistics_specs(qty, prod['dims_cm'], prod['weight_kg'], packing_type)

    # 1. 물류비 계산 (기본 운임 x KCCI 지수)
    # 가정: 부산 -> 홍콩/일본 기준 기본 운임표 (실무에선 DB화 필요)
    base_rate_ocean_lcl = 60000 # KRW per R/T (CBM)
    base_rate_ocean_fcl_20 = 1500000 # KRW per 20ft
    base_rate_ocean_fcl_40 = 2800000 # KRW per 40ft
    base_rate_air = 3500 # KRW per kg

    # A. Ocean LCL
    cost_ocean_lcl = ocean_rt * base_rate_ocean_lcl * kcci_index

    # B. Ocean FCL (컨테이너 수량 산출)
    # 20ft: approx 28 CBM, 40ft: approx 58 CBM
    req_20ft = math.ceil(total_cbm / 28)
    req_40ft = math.ceil(total_cbm / 58)
    
    cost_ocean_fcl_20 = req_20ft * base_rate_ocean_fcl_20 * kcci_index
    cost_ocean_fcl_40 = req_40ft * base_rate_ocean_fcl_40 * kcci_index
    
    # FCL 최적가 선정
    if cost_ocean_fcl_20 < cost_ocean_fcl_40:
        cost_ocean_fcl_opt = cost_ocean_fcl_20
        fcl_desc = f"20ft x {req_20ft}대"
    else:
        cost_ocean_fcl_opt = cost_ocean_fcl_40
        fcl_desc = f"40ft x {req_40ft}대"

    # C. Air Freight
    cost_air = air_cw * base_rate_air * kcci_index

    # ---------------------------------------------------------
    # TAB UI 구성
    # ---------------------------------------------------------
    tab1, tab2, tab3 = st.tabs(["🚛 최적 물류 루트 (Logistics)", "💰 수출 가격 & 인코텀즈 (Price)", "📊 실시간 대시보드"])

    # --- TAB 1: 물류 루트 비교 ---
    with tab1:
        st.subheader("📦 최적 운송 루트 분석 (Optimization)")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("총 선적 부피 (Volume)", f"{total_cbm:.2f} CBM", 
                      delta="LCL 적합" if total_cbm < 15 else "FCL 전환 고려", delta_color="inverse")
        with col2:
            st.metric("총 선적 중량 (Weight)", f"{total_gw:,.0f} kg")
        with col3:
            st.metric("KCCI 변동 지수", f"{kcci_index}x", "시장 운임 상승 반영됨")

        st.markdown("---")
        
        # 루트별 비용 카드
        c1, c2, c3 = st.columns(3)
        
        # 1. Ocean LCL
        c1.info(f"🚢 **Ocean LCL** (소량 화물)")
        c1.write(f"비용: ₩{cost_ocean_lcl:,.0f}")
        c1.caption(f"기준: {ocean_rt:.2f} R/T 적용")
        
        # 2. Ocean FCL
        if cost_ocean_fcl_opt < cost_ocean_lcl:
            c2.success(f"🛳️ **Ocean FCL** (추천)")
        else:
            c2.warning(f"🛳️ **Ocean FCL**")
        c2.write(f"비용: ₩{cost_ocean_fcl_opt:,.0f}")
        c2.caption(f"필요: {fcl_desc}")

        # 3. Air
        c3.error(f"✈️ **Air Freight** (긴급)")
        c3.write(f"비용: ₩{cost_air:,.0f}")
        c3.caption(f"Chargeable Weight: {air_cw:,.0f} kg")

        # 비교 차트
        logistics_data = pd.DataFrame({
            "Mode": ["Ocean LCL", "Ocean FCL", "Air Freight"],
            "Cost (KRW)": [cost_ocean_lcl, cost_ocean_fcl_opt, cost_air]
        })
        fig = px.bar(logistics_data, x="Mode", y="Cost (KRW)", color="Mode", title="운송 모드별 예상 비용 비교")
        st.plotly_chart(fig, use_container_width=True)

    # --- TAB 2: 가격 및 인코텀즈 ---
    with tab2:
        st.subheader(f"💰 {incoterms} 조건 수출 가격 시뮬레이션")

        # 비용 항목 정의 (단위: KRW)
        cost_mfg = prod['cost_mfg'] * qty  # 총 제조원가
        margin = cost_mfg * 0.3  # 마진 30% 가정
        
        # 부대비용 (가정치)
        cost_packing = 500 * qty
        cost_inland_kr = 250000 # 국내 운송
        cost_customs_kr = 50000 # 통관비
        cost_terminal_kr = 100000 # THC 등
        
        # 국제 운송비 (가장 저렴한 해상 운임 적용)
        main_freight = min(cost_ocean_lcl, cost_ocean_fcl_opt)
        insurance = main_freight * 0.002 # 보험료 0.2%
        
        # 도착지 비용 (홍콩 기준)
        cost_terminal_dest = 150000
        cost_customs_dest = 50000
        duty_rate = 0 if target_market == "Hong Kong" else 0.1 # 홍콩 관세 0%
        cost_duty = (cost_mfg + margin + main_freight) * duty_rate
        cost_inland_dest = 300000

        # 인코텀즈별 판매자 부담 비용 계산 로직
        costs = {
            "Product": cost_mfg + margin,
            "Packing": cost_packing,
            "Inland(KR)": cost_inland_kr,
            "Customs(KR)": cost_customs_kr,
            "Terminal(KR)": cost_terminal_kr,
            "Freight": main_freight,
            "Insurance": insurance,
            "Terminal(Dest)": cost_terminal_dest,
            "Customs(Dest)": cost_customs_dest,
            "Duty": cost_duty,
            "Inland(Dest)": cost_inland_dest
        }

        # 인코텀즈 로직 매핑 (True=Seller Pays)
        incoterm_rules = {
            "EXW": ["Product", "Packing"],
            "FOB": ["Product", "Packing", "Inland(KR)", "Customs(KR)", "Terminal(KR)"],
            "CFR": ["Product", "Packing", "Inland(KR)", "Customs(KR)", "Terminal(KR)", "Freight"],
            "CIF": ["Product", "Packing", "Inland(KR)", "Customs(KR)", "Terminal(KR)", "Freight", "Insurance"],
            "DDP": list(costs.keys())
        }

        seller_pays = 0
        buyer_pays = 0
        
        breakdown_list = []

        for item, amount in costs.items():
            is_seller_paid = item in incoterm_rules[incoterms]
            payer = "판매자 (Seller)" if is_seller_paid else "바이어 (Buyer)"
            if is_seller_paid:
                seller_pays += amount
            else:
                buyer_pays += amount
            
            breakdown_list.append({"항목": item, "금액 (KRW)": amount, "부담 주체": payer})

        # 결과 출력
        col_res1, col_res2 = st.columns(2)
        with col_res1:
            st.markdown(f"#### 📤 수출 견적가 ({incoterms})")
            quote_krw = seller_pays
            quote_usd = quote_krw / usd_rate
            
            st.metric("총 견적 금액 (KRW)", f"₩{quote_krw:,.0f}")
            st.metric("총 견적 금액 (USD)", f"${quote_usd:,.2f}")
            st.caption(f"적용 환율: 1 USD = {usd_rate} KRW")

        with col_res2:
            st.markdown(f"#### 📥 바이어 예상 총 비용")
            total_buyer_cost = seller_pays + buyer_pays
            st.metric("Landed Cost (도착 원가)", f"₩{total_buyer_cost:,.0f}")
            if target_market == "Hong Kong":
                 st.metric("Landed Cost (HKD)", f"HK$ {total_buyer_cost / hkd_rate:,.2f}")
        
        st.table(pd.DataFrame(breakdown_list))

    # --- TAB 3: 실시간 대시보드 ---
    with tab3:
        st.metric("현재 KCCI 물류 지수", f"{kcci_index}", "전월 대비 +0.05")
        st.metric("현재 환율 (USD)", f"{usd_rate}", f"전일 대비 변동")

if __name__ == "__main__":
    main()
