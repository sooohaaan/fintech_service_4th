from io import StringIO
import requests

############ 1. 환경 설정 및 라이브러리 불러오기 ############
import sys
import os
import time
import io
import pandas as pd
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

# 외부 모듈 'dbio' 경로 설정
# 상위 폴더(../../)에 있는 dbio.py 파일을 임포트하기 위해 경로를 sys.path에 추가
target_dir = os.path.abspath('../../')
if target_dir not in sys.path:
    sys.path.append(target_dir)
from dbio import to_db


############ 2. 브라우저 설정 ############
options = Options()
options.add_argument("--window-size=1280,1000")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
wait = WebDriverWait(driver, 10)


############ 3. 수집 기간 리스트 설정 ############
# 수집할 데이터의 시작일과 종료일 설정
start_target = datetime(2026, 1, 30)  # 마지막 날짜
end_target = datetime(2026, 1, 1)     # 시작 날짜
# 영업일 기준으로 날짜 범위 생성
search_days = pd.bdate_range(start=end_target, end=start_target)

# 수집된 데이터를 저장할 리스트
result = []
# 수집 실패한 날짜를 기록할 리스트
failed_dates = []


############## 4. 컬럼명 평탄화 함수 ##############
def flatten_and_clean_columns(df):
    new_columns = []
    
    for col in df.columns:
        # 컬럼이 tuple 형태인지 확인 (MultiIndex의 경우)
        if isinstance(col, tuple):
            # tuple의 각 요소를 문자열로 변환
            parts = []
            for c in col:
                c_str = str(c).strip()  # 문자열로 변환 후 공백 제거
                # NaN, None, 빈 문자열 제외
                if c_str and c_str.lower() not in ['nan', 'none', '']:
                    parts.append(c_str)
            
            # 중복 제거 (순서는 유지)
            # 예: ['통화', '통화', '통화'] → ['통화']
            unique_parts = []
            for p in parts:
                if p not in unique_parts:
                    unique_parts.append(p)
            
            # 컬럼명 생성
            if unique_parts:
                # 리스트를 '_'로 연결하고 공백을 '_'로 치환
                # 예: ['현찰', '사실 때', '환율'] → '현찰_사실_때_환율'
                col_name = "_".join(unique_parts).replace(" ", "_")
            else:
                # 모든 요소가 제거된 경우 기본 이름 사용
                col_name = "unknown_col"
        else:
            # tuple이 아닌 경우 (일반 컬럼명)
            # 문자열로 변환하고 공백을 '_'로 치환
            col_name = str(col).replace(" ", "_")
        
        new_columns.append(col_name)
    
    # DataFrame의 컬럼을 새로운 컬럼명 리스트로 직접 교체
    # (이 방식이 rename()보다 확실함)
    df.columns = new_columns
    return df


########### 5. 하나은행 환율 데이터 수집 메인 프로세스 ############
try:
    # 영업일 리스트를 순회하며 각 날짜별 데이터 수집
    for date_obj in search_days:
        
        # 날짜를 'YYYYMMDD' 형식의 문자열로 변환
        search_date = date_obj.strftime("%Y%m%d")
        print(f"\n[작업 시작]📅{end_target} ~ {start_target} / {search_date} 환율 조회를 시도합니다.")
        
        # (1) 하나은행 환율 페이지 접속
        driver.get("https://www.kebhana.com/cms/rate/index.do?contentUrl=/cms/rate/wpfxd651_01i.do#//HanaBank")
        # 페이지 로딩 완료를 위해 2초 대기
        time.sleep(2)

        # (2) 날짜 입력 필드 찾기 및 활성화
        # CSS 선택자로 'tmpInqStrDt' ID를 가진 input 요소가 나타날 때까지 최대 10초 대기
        search_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input#tmpInqStrDt')))

        # (3) 기존에 입력되어 있던 날짜 제거
        # Ctrl+A로 전체 선택
        search_input.send_keys(Keys.CONTROL + "a")
        # Backspace로 삭제
        search_input.send_keys(Keys.BACKSPACE)

        # (4) 조회할 날짜 입력
        # 예: '20260101'
        search_input.send_keys(search_date)

        # (5) '조회' 버튼 클릭
        # 'a.btnDefault.bg' CSS 선택자를 가진 요소가 클릭 가능할 때까지 대기
        search_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'a.btnDefault.bg')))
        search_button.click()
        # 검색 결과 로딩을 위해 3초 대기
        time.sleep(3)

        # (6) HTML 소스 추출 및 테이블 파싱
            # (❗) pandas 3.0에서 lxml 관련 오류 발생
            # ==> 이를 해결하기 위해 flavor='html5lib' 사용
            # (❗) html 소스를 경로로 인식하는 문제 발생
            # ==> 이를 해결하기 위해 StringIO 사용

        # 현재 페이지의 HTML 소스 가져오기
        html_source = driver.page_source

        # 문자열을 스트림 객체로 변환
        html_stream = io.StringIO(html_source)

        # html5lib 파서를 지정하여 테이블 파싱
        tables = pd.read_html(html_stream, flavor='html5lib')

        # 디버깅: 발견된 테이블 개수 출력
        print(f"🔎발견된 테이블 개수: {len(tables)}")

        # (7) 실제 환율 테이블 찾기
        # 페이지에 여러 테이블이 있을 수 있으므로 조건에 맞는 것을 찾아야 함
        df_exchange = None
        for i, table in enumerate(tables):
            # 환율 테이블 판별 조건
            # 행(row)이 5개 이상
            # 컬럼명이나 첫 행에 '통화' 또는 '매매' 키워드 포함
            if table.shape[0] > 5:
                col_str = str(table.columns)  # 컬럼명을 문자열로 변환
                first_row = table.iloc[0].to_string() if len(table) > 0 else ""  # 첫 행을 문자열로

                # '통화' 또는 '매매' 키워드가 있으면 환율 테이블로 판단
                if '통화' in (col_str + first_row) or '매매' in (col_str + first_row):
                    df_exchange = table.copy()  # 테이블 복사
                    print(f"  ✓ 환율 테이블 선택: 테이블 {i} (shape: {table.shape})")
                    break  # 찾았으면 루프 종료

        # (8) 환율 테이블을 찾지 못한 경우
        if df_exchange is None:
            print(f" ❌ {search_date} 실패: 환율 테이블을 찾을 수 없습니다.")
            failed_dates.append(search_date)  # 실패 날짜 기록
            continue  # 다음 날짜로 넘어감

        # (9) 빈 테이블 검증
        if df_exchange.empty:
            print(f"❌ {search_date} 건너뜀: 빈 테이블")
            failed_dates.append(search_date)
            continue

        # (10) 컬럼명 평탄화
        # MultiIndex 컬럼을 단일 문자열로 변환
        df_exchange = flatten_and_clean_columns(df_exchange)

        # (12) DB 저장 시도
        # dbio 모듈의 to_db 함수를 사용하여 MySQL DB에 저장
        # 데이터베이스: exchange_rate_data_selenium
        # 테이블: exchange_rate
        to_db("exchange_rate_data_selenium_exe", "exchange_rate", df_exchange)
        result.append(df_exchange)
        print(f"✓ {search_date} 성공: {len(df_exchange)}건 수집 완료")


    ############ 6. 최종 통합 처리 ############
    print("\n" + "="*60)
    
    # 수집된 데이터가 있는 경우
    if result:
        # 모든 날짜의 DataFrame을 하나로 통합
        final_df = pd.concat(result, ignore_index=True)
        print(f"✅ 전체 작업 완료! 총 {len(final_df)}건의 데이터가 통합되었습니다.")
        
        # 실패한 날짜가 있으면 출력
        if failed_dates:
            print(f"\n🪦 실패한 날짜 ({len(failed_dates)}개):")
            print(f"   {', '.join(failed_dates)}")


############ 7. 종료 ############
finally:
    # 브라우저 종료
    driver.quit()
    print("\n 🕊️안전하게 종료했습니다.✌️")
    print("="*60 + "\n")