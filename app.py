# 1. 필수 라이브러리 설치 (구글 콜랩에서는 이 줄을 가장 먼저 실행하세요)
# !pip install streamlit pandas plotly

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# ==========================================
# 1. 데이터 베이스 (분트카키 설정)
# ==========================================
PRODUCTS = {
    "9in1 모듈 쉘프": {
        "price_retail_krw": 199000,
        "cost_mfg": 60000, # 제조원가
        "weight_kg": 6.0,
        "cbm_unit": 0.027, # 30x30x30cm
        "hs_code": "9403.70"
    },
    "베를린 테이블": {
        "price_retail_krw": 450000, # 임의 설정
        "cost_mfg": 135000, # 30% 가정
        "weight_kg": 19.0,
        "cbm_unit": 0.125, # 50x50x50cm
        "hs_code": "9403.60"
    }
}

# ==========================================
# 2. UI 및 로직 구현
# ==========================================
def main():
    st.set_page_config(layout="wide", page_title="Buntkaki Export Simulator")

    # [사이드바] 기본 설정
    st.sidebar.title("🔧 Export Settings")
    target_market = st.sidebar.selectbox("타겟 국가", ["Japan (일본)", "Hong Kong (홍콩)"])
    currency_rate = st.sidebar.number_input("현재 환율 (1USD)", value=1460)
    yen_rate = st.sidebar.number_input("현재 엔화 (100JPY)", value=933)
    
    # 탭 구분 (사진처럼 물류와 가격을 나눔)
    tab1, tab2 = st.tabs(["🚛 LOGISTICS PRO", "💰 PRICE SIMULATOR"])

    # ---------------------------------------------------------
    # TAB 1: LOGISTICS PRO (물류 전략)
    # ---------------------------------------------------------
    with tab1:
        st.markdown("### 📦 Shipment Strategy")
        
        # 1-1. 선적 데이터 입력 (사진 3번 구현)
        with st.container(border=True):
            col1, col2, col3 = st.columns(3)
            with col1:
                product_sel = st.selectbox("제품 선택", list(PRODUCTS.keys()))
                packing_type = st.radio("포장 방식", ["모듈 상태 (부피 30% 절감)", "완제품 (부피 100%)"], horizontal=True)
            with col2:
                qty = st.number_input("선적 수량 (PCS)", value=500, step=50)
                incoterms = st.selectbox("인코텀즈", ["FOB", "CIF", "DDP"])
            with col3:
                # 자동 계산 로직
                prod_info = PRODUCTS[product_sel]
                cbm_factor = 0.7 if "모듈" in packing_type else 1.0
                total_cbm = round(prod_info['cbm_unit'] * qty * cbm_factor, 2)
                total_weight = prod_info['weight_kg'] * qty
                
                st.metric("총 중량 (Weight)", f"{total_weight:,.0f} kg")
                st.metric("총 부피 (Volume)", f"{total_cbm} CBM", delta="LCL 적용" if total_cbm < 15 else "FCL(20ft) 추천")

        # 1-2. 비용 비교 카드 (사진 2번 구현)
        st.markdown("#### ✈️ Logistics Cost Comparison")
        
        # 가상의 운임 계산 (실제 API 연동 대신 로직 적용)
        ocean_cost = 150000 + (total_cbm * 65000) # 기본료 + CBM당 비용
        ferry_cost = 200000 + (total_cbm * 110000)
        air_cost = 300000 + (total_weight * 4500) # kg당 비용

        c1, c2, c3 = st.columns(3)
        with c1:
            st.info(f"🚢 SEA LCL\n\n**${ocean_cost/currency_rate:,.0f}**\n\n(약 {ocean_cost:,.0f} 원)")
        with c2:
            st.success(f"🛳️ FAST FERRY (추천)\n\n**${ferry_cost/currency_rate:,.0f}**\n\n(약 {ferry_cost:,.0f} 원)")
        with c3:
            st.warning(f"✈️ AIR CARGO\n\n**${air_cost/currency_rate:,.0f}**\n\n(약 {air_cost:,.0f} 원)")

        # 1-3. 비용 구성 도넛 차트 (사진 2번 하단)
        col_chart, col_detail = st.columns([1, 1])
        with col_chart:
            labels = ['기본 운임', '유류할증료(BAF)', '터미널핸들링(THC)', '서류/보험료']
            values = [ocean_cost*0.6, ocean_cost*0.1, ocean_cost*0.2, ocean_cost*0.1]
            fig = px.pie(values=values, names=labels, hole=0.5, title="비용 구성 (Sea LCL 기준)")
            st.plotly_chart(fig, use_container_width=True)
            
        with col_detail:
            st.markdown("##### 📋 책임 비용 상세 내역 (Export Side)")
            st.dataframe(pd.DataFrame({
                "항목": labels,
                "금액(KRW)": [f"{v:,.0f}" for v in values]
            }), hide_index=True)

    # ---------------------------------------------------------
    # TAB 2: PRICE SIMULATOR (가격 시뮬레이터)
    # ---------------------------------------------------------
    with tab2:
        st.markdown("### 💰 Export Price Structure")
        
        # 2-1. 가격 설정 (사진 1번 구현)
        with st.expander("가격 변수 설정 (클릭하여 펼치기)", expanded=True):
            pc1, pc2, pc3 = st.columns(3)
            with pc1:
                target_margin = st.slider("제조사 희망 마진 (%)", 10, 50, 25)
            with pc2:
                buyer_margin_rate = st.number_input("바이어 희망 마진 (%)", 40, 70, 50)
            with pc3:
                # 관세율 자동 설정
                duty_rate = 0 if "Hong Kong" in target_market else 0  # 일본 가구(9403) 보통 무관세이나 확인필요
                tax_rate = 0 if "Hong Kong" in target_market else 10 # 일본 소비세 10%
                st.caption(f"관세: {duty_rate}%, 부가세: {tax_rate}% 적용됨")

        # 계산 로직
        cost = prod_info['cost_mfg']
        exw_price = cost * (1 + target_margin/100)
        
        # 물류비 배분 (개당)
        logistics_per_unit = ocean_cost / qty
        
        # 인코텀즈별 가격
        fob_price = exw_price + (2000) # 내륙운송비 가정
        cif_price = fob_price + logistics_per_unit
        ddp_price = cif_price * (1 + duty_rate/100) + (cif_price * 0.03) # 통관비 등

        # 바이어 판매가 역산
        landed_cost = ddp_price
        retail_price_simulated = landed_cost / (1 - buyer_margin_rate/100)

        # 2-2. 최종 견적 카드 (사진 1번 중앙)
        st.divider()
        qc1, qc2 = st.columns([2, 1])
        with qc1:
            st.markdown(f"""
            <div style="background-color:#e6f3ff; padding:20px; border-radius:10px;">
                <h2 style="color:#0068c9; margin:0;">CIF QUOTE: ${cif_price/currency_rate:,.2f}</h2>
                <p>개당 한화 환산: {cif_price:,.0f} 원</p>
            </div>
            """, unsafe_allow_html=True)
        with qc2:
            profit = exw_price - cost
            st.markdown(f"""
            <div style="background-color:#f0f2f6; padding:20px; border-radius:10px;">
                <h3 style="color:#262730; margin:0;">예상 영업이익</h3>
                <h2 style="color:#09ab3b; margin:0;">₩{profit:,.0f}</h2>
            </div>
            """, unsafe_allow_html=True)

        # 2-3. 상세 가격 구성표 (사진 1번 하단 테이블)
        st.markdown("#### 🧾 상세 가격 구성표 (Breakdown)")
        
        breakdown_data = {
            "구분": ["제품 공급가 (EXW)", "국내 물류 (Inland)", "국제 운임 (Freight)", "도착지 관세 (Duty)", "도착지 부가세 (Tax)", "바이어 마진", "최종 소비자가"],
            "세부 내역": ["제조원가 + 제조사마진", "부산항 운송료", "해상운임 + 보험", f"수입관세 ({duty_rate}%)", f"소비세 ({tax_rate}%)", "유통채널 마진", "현지 판매가"],
            "금액 (KRW)": [
                exw_price, 2000, logistics_per_unit, 
                cif_price * (duty_rate/100), 
                (cif_price + (cif_price * duty_rate/100)) * (tax_rate/100),
                retail_price_simulated - landed_cost - ((cif_price + (cif_price * duty_rate/100)) * (tax_rate/100)),
                retail_price_simulated
            ]
        }
        
        df_breakdown = pd.DataFrame(breakdown_data)
        # 천단위 콤마 포맷팅
        df_breakdown["금액 (KRW)"] = df_breakdown["금액 (KRW)"].apply(lambda x: f"₩{x:,.0f}")
        
        st.dataframe(df_breakdown, use_container_width=True, hide_index=True)

        # 2-4. 리스크 알림 (분트카키 특화)
        st.divider()
        logistics_ratio = (logistics_per_unit / fob_price) * 100
        
        if logistics_ratio > 20:
            st.error(f"⚠️ 물류비 비중 경고: {logistics_ratio:.1f}% (상한선 20% 초과) → MOQ를 늘리거나 모듈 포장을 고려하세요.")
        else:
            st.success(f"✅ 물류비 비중 안정: {logistics_ratio:.1f}% (적정 범위)")

if __name__ == "__main__":
    main()
