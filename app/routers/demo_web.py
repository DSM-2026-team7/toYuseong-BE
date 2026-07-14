from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/demo", tags=["demo-web"])

# 토스페이먼츠 공식 테스트용 클라이언트 키
TOSS_CLIENT_KEY = "test_ck_G2p9LL2p3kv22409oOnr3b7YxAdX"

@router.get("/purchase", response_class=HTMLResponse)
def get_purchase_demo():
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>투유성 패스 구매 데모</title>
        <script src="https://js.tosspayments.com/v1/payment"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            body {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                background-color: #f3f4f6;
                margin: 0;
                padding: 40px 20px;
                display: flex;
                flex-direction: column;
                align-items: center;
            }}
            .card {{
                background: white;
                padding: 30px;
                border-radius: 16px;
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
                max-width: 480px;
                width: 100%;
            }}
            h1 {{
                font-size: 24px;
                font-weight: 700;
                color: #111827;
                margin-top: 0;
                margin-bottom: 20px;
                text-align: center;
            }}
            .form-group {{
                margin-bottom: 18px;
            }}
            label {{
                display: block;
                font-size: 14px;
                font-weight: 600;
                color: #374151;
                margin-bottom: 6px;
            }}
            input, select {{
                width: 100%;
                padding: 10px 12px;
                border: 1px solid #d1d5db;
                border-radius: 8px;
                font-size: 15px;
                box-sizing: border-box;
            }}
            .btn {{
                width: 100%;
                background-color: #3182f6;
                color: white;
                border: none;
                padding: 12px;
                border-radius: 8px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: background-color 0.2s;
                margin-top: 10px;
            }}
            .btn:hover {{
                background-color: #1b64da;
            }}
            .result-box {{
                margin-top: 20px;
                padding: 15px;
                border-radius: 8px;
                background-color: #f9fafb;
                border: 1px solid #e5e7eb;
                font-family: monospace;
                white-space: pre-wrap;
                word-break: break-all;
                display: none;
                font-size: 13px;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🎫 패스 구매 데모</h1>
            <div class="form-group">
                <label for="userId">테스트할 User ID (X-User-Id)</label>
                <input type="number" id="userId" value="1">
            </div>
            <div class="form-group">
                <label for="passSelect">구매할 패스 선택</label>
                <select id="passSelect">
                    <option value="">패스 목록 불러오는 중...</option>
                </select>
            </div>
            <button class="btn" onclick="requestPayment()">토스페이로 결제하기</button>
            <div class="result-box" id="resultBox"></div>
        </div>

        <script>
            const tossPayments = TossPayments("{TOSS_CLIENT_KEY}");
            let passes = [];

            // 패스 목록 불러오기
            async function loadPasses() {
                try {
                    const res = await fetch('/passes');
                    const data = await res.json();
                    passes = data.passes;
                    const select = document.getElementById('passSelect');
                    select.innerHTML = '';
                    passes.forEach(p => {
                        const opt = document.createElement('option');
                        opt.value = p.id;
                        opt.textContent = `${p.name} - ${p.price.toLocaleString()}원 (${p.duration_days}일)`;
                        select.appendChild(opt);
                    });
                } catch (err) {
                    console.error("패스 목록 로드 실패", err);
                }
            }

            async function requestPayment() {
                const userId = document.getElementById('userId').value;
                const passId = document.getElementById('passSelect').value;
                if (!passId) return alert("패스를 선택해 주세요.");

                const selectedPass = passes.find(p => p.id == passId);
                const orderId = "pass_" + userId + "_" + passId + "_" + Date.now();
                
                // 로컬 스토리지에 세션 저장 (토스 완료 리다이렉트 후 복구용)
                localStorage.setItem("toss_demo_purchase", JSON.stringify({
                    userId: userId,
                    passId: passId,
                    amount: selectedPass.price,
                    duration_days: selectedPass.duration_days
                }));

                tossPayments.requestPayment('카드', {
                    amount: selectedPass.price,
                    orderId: orderId,
                    orderName: selectedPass.name,
                    successUrl: window.location.origin + '/demo/success?type=pass',
                    failUrl: window.location.origin + '/demo/fail'
                });
            }

            window.onload = loadPasses;
        </script>
    </body>
    </html>
    """
    return html_content

@router.get("/success", response_class=HTMLResponse)
def get_success_page(type: str, paymentKey: str, orderId: str, amount: int):
    # 토스 인증 완료 후 이곳으로 리다이렉트됨. 백엔드 승인 API를 즉시 호출
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <title>결제 처리 중...</title>
        <style>
            body {{ font-family: sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; background-color: #f3f4f6; margin: 0; }}
            .loader {{ border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
            .card {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); text-align: center; max-width: 450px; width: 90%; }}
            pre {{ text-align: left; background: #2d3748; color: #a0aec0; padding: 15px; border-radius: 8px; overflow-x: auto; font-size: 13px; }}
            .btn {{ display: inline-block; background-color: #3182f6; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: bold; margin-top: 15px; }}
        </style>
    </head>
    <body>
        <div class="card" id="card">
            <div class="loader" id="loader"></div>
            <h2 id="statusTitle">결제를 승인하고 있어요...</h2>
            <p id="statusMsg">토스페이먼츠 및 백엔드 트랜잭션을 마무리 중입니다.</p>
            <div id="resultBox" style="display:none;">
                <pre id="jsonResult"></pre>
                <a href="/demo/purchase" class="btn">🎫 데모 페이지로 이동</a>
            </div>
        </div>

        <script>
            async function confirmPayment() {
                const type = "{type}";
                const paymentKey = "{paymentKey}";
                const orderId = "{orderId}";
                const amount = {amount};

                const loader = document.getElementById('loader');
                const statusTitle = document.getElementById('statusTitle');
                const statusMsg = document.getElementById('statusMsg');
                const resultBox = document.getElementById('resultBox');
                const jsonResult = document.getElementById('jsonResult');

                if (type === 'pass') {
                    const session = JSON.parse(localStorage.getItem("toss_demo_purchase") || "{{}}");
                    if (!session.userId || !session.passId) {
                        statusTitle.textContent = "에러 발생";
                        statusMsg.textContent = "세션 정보가 유실되었습니다.";
                        loader.style.display = 'none';
                        return;
                    }

                    try {
                        const response = await fetch(`/passes/${{session.passId}}/purchase`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-User-Id': session.userId
                            },
                            body: JSON.stringify({
                                duration_days: session.duration_days,
                                paymentKey: paymentKey,
                                orderId: orderId,
                                amount: amount
                            })
                        });

                        const result = await response.json();
                        loader.style.display = 'none';

                        if (response.ok) {
                            statusTitle.textContent = "🎉 패스 구매 및 결제 완료!";
                            statusMsg.textContent = "토스페이 승인 성공 및 로컬 DB 반영 완료";
                            jsonResult.textContent = JSON.stringify(result, null, 2);
                        } else {
                            statusTitle.textContent = "❌ 결제 승인 실패";
                            statusMsg.textContent = result.detail?.message || "알 수 없는 에러";
                            jsonResult.textContent = JSON.stringify(result, null, 2);
                        }
                        resultBox.style.display = 'block';
                    } catch (err) {
                        loader.style.display = 'none';
                        statusTitle.textContent = "통신 실패";
                        statusMsg.textContent = err.message;
                        resultBox.style.display = 'block';
                    }
                }
            }

            confirmPayment();
        </script>
    </body>
    </html>
    """
    return html_content

@router.get("/fail", response_class=HTMLResponse)
def get_fail_page(code: str, message: str, orderId: str):
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <title>결제 실패</title>
        <style>
            body {{ font-family: sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; background-color: #f3f4f6; margin: 0; }}
            .card {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); text-align: center; max-width: 450px; width: 90%; }}
            .btn {{ display: inline-block; background-color: #e53e3e; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: bold; margin-top: 15px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2 style="color: #e53e3e;">❌ 결제가 거절되거나 취소되었습니다</h2>
            <p>코드: {code}</p>
            <p>메시지: {message}</p>
            <p>주문번호: {orderId}</p>
            <a href="/demo/purchase" class="btn">🎫 데모 페이지로 이동</a>
        </div>
    </body>
    </html>
    """
    return html_content
