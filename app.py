import os
import asyncio
import logging
import traceback
from datetime import datetime, timezone

from flask import Flask, request, abort, jsonify
from linebot.v3.messaging import MessagingApi, Configuration, ApiClient, PushMessageRequest, TextMessage, ReplyMessageRequest, FlexMessage, FlexBubble, FlexBox, FlexText, FlexButton, MessageAction, URIAction, FlexImage, FlexSeparator
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent
from linebot.v3.exceptions import InvalidSignatureError
import random

import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv

if os.path.exists('.env'):
    load_dotenv()
    print("✅ 載入本地 .env 配置")
else:
    print("🚀 使用生產環境配置")

# 設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# 初始化
app = Flask(__name__)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
try:
    # 檢查是否為本地開發環境
    if os.path.exists('.env'):
        # 本地開發：直接讀取 JSON 檔案
        json_files = [f for f in os.listdir('.') if
                      f.startswith('smartlearninglinebot-firebase-adminsdk') and f.endswith('.json')]
        if json_files:
            firebase_key_path = json_files[0]  # 取第一個找到的檔案
            cred = credentials.Certificate(firebase_key_path)
            logger.info(f"使用本地 Firebase 憑證檔案: {firebase_key_path}")
        else:
            raise ValueError("找不到 Firebase 憑證檔案")
    else:
        # 生產環境：從環境變數讀取
        firebase_credentials = os.environ.get('FIREBASE_CREDENTIALS')
        if firebase_credentials:
            import json

            cred_dict = json.loads(firebase_credentials)

            # 修正私鑰格式
            if 'private_key' in cred_dict:
                private_key = cred_dict['private_key']
                if '\\n' in private_key:
                    cred_dict['private_key'] = private_key.replace('\\n', '\n')

            cred = credentials.Certificate(cred_dict)
            logger.info("使用環境變數 Firebase 憑證")
        else:
            raise ValueError("找不到 Firebase 憑證")

    firebase_admin.initialize_app(cred)
    db = firestore.client()
    logger.info("Firebase Admin SDK 初始化成功")
except Exception as e:
    logger.error(f"Firebase Admin SDK 初始化失敗: {e}")
    db = None
class UserManager:
    @staticmethod
    def record_user_id(user_id):
        try:
            user_ref = db.collection('Users').document(user_id)
            user_doc = user_ref.get()

            if not user_doc.exists:
                # 創建新用戶資料
                user_data = {
                    "user_id": user_id,
                    "created_at": datetime.now(timezone.utc),
                    "last_active": datetime.now(timezone.utc)
                }
                user_ref.set(user_data)
                logger.info(f"記錄新 user_id: {user_id}")
            else:
                # 更新最後活躍時間
                user_ref.update({
                    "last_active": datetime.now()
                })
                logger.info(f"更新 user_id 活躍時間: {user_id}")

        except Exception as e:
            logger.error(f"記錄用戶 ID 失敗: {e}")

    @staticmethod
    def get_all_user_ids():
        try:
            users_ref = db.collection('Users')
            docs = users_ref.stream()
            return [doc.id for doc in docs]
        except Exception as e:
            logger.error(f"獲取用戶 ID 列表失敗: {e}")
            return []

class MessageService:
    @staticmethod
    def send_message_to_user(user_id, message):
        configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            try:
                # 判斷是否為學習報告（包含特定關鍵字）
                if any(keyword in message for keyword in ["🎓 學習報告", "學習態度", "學習成效", "學習專心度"]):
                    flex_bubble = create_learning_report_flex(message)
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=user_id,
                            messages=[FlexMessage(alt_text="學習報告", contents=flex_bubble)]
                        )
                    )
                else:
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=user_id,
                            messages=[TextMessage(text=message)]
                        )
                    )
                return True
            except Exception as e:
                logger.error(f"推送訊息給 {user_id} 失敗: {e}")
                return False

    @staticmethod
    def broadcast_message(message):
        user_ids = UserManager.get_all_user_ids()
        if not user_ids:
            return {"status": "no_users", "user_count": 0}

        success_count = 0
        for user_id in user_ids:
            if MessageService.send_message_to_user(user_id, message):
                success_count += 1

        return {"status": "ok", "user_count": len(user_ids), "success_count": success_count}


class LearningReportGenerator:
    @staticmethod
    def generate_fake_data():
        return {
            'totalTime': round(random.uniform(600, 3600), 1),  # 10-60分鐘
            'attitudeScore': round(random.uniform(40, 95), 1),
            'effectivenessScore': round(random.uniform(45, 98), 1),
            'concentrationScore': round(random.uniform(35, 90), 1),
            'correctCount': random.randint(3, 15),
            'wrongCount': random.randint(0, 8),
            'unansweredCount': random.randint(0, 5),
            'totalQuestions': lambda data: data['correctCount'] + data['wrongCount'] + data['unansweredCount'],
            'avgAnswerTime': round(random.uniform(8, 45), 1)
        }

    @staticmethod
    def generate_learning_message(data):
        # 處理 totalQuestions 的計算
        if callable(data['totalQuestions']):
            data['totalQuestions'] = data['totalQuestions'](data)

        total_time = data['totalTime']
        attitude_score = data['attitudeScore']
        effectiveness_score = data['effectivenessScore']
        concentration_score = data['concentrationScore']
        correct_count = data['correctCount']
        wrong_count = data['wrongCount']
        unanswered_count = data['unansweredCount']
        total_questions = data['totalQuestions']
        avg_answer_time = data['avgAnswerTime']

        def get_star_rating(score):
            filled_stars = max(1, min(5, round(score / 20)))
            empty_stars = 5 - filled_stars
            return "⭐" * filled_stars + "☆" * empty_stars

        message = "🎓 學習報告出爐啦！\n\n"

        # 學習態度分析
        message += f"❶學習態度{get_star_rating(attitude_score)} ({attitude_score:.1f}分)\n"
        if attitude_score >= 80:
            message += "🌟 超棒！你的專注力像雷射一樣集中！\n"
        elif attitude_score >= 60:
            message += "👍 不錯喔！保持這個節奏繼續加油！\n"
        else:
            message += "🤔 似乎有點分心呢，試著找個更安靜的環境吧！\n"

        message += f"⏰ 總學習時間：{total_time / 60:.1f}分鐘\n\n"

        # 學習成效分析
        message += f"❷學習成效{get_star_rating(effectiveness_score)} ({effectiveness_score:.1f}分)\n"
        if effectiveness_score >= 90:
            message += "🏆 太厲害了！你是學霸本霸！\n"
        elif effectiveness_score >= 70:
            message += "✨ 表現很好！再接再厲就能更上一層樓！\n"
        elif effectiveness_score >= 50:
            message += "💡 還有進步空間，建議重新複習一下重點內容！\n"
        else:
            message += "📚 別灰心！學習是個過程，建議先回去看看PDF內容！\n"

        message += f"✅ 答對：{correct_count}題\n❌ 答錯：{wrong_count}題\n"
        if unanswered_count > 0:
            message += f"⏸️ 未作答：{unanswered_count}題\n"

        message += "\n"

        # 學習專心度分析
        message += f"❸學習專心度{get_star_rating(concentration_score)} ({concentration_score:.1f}分)\n"
        if avg_answer_time <= 10:
            message += "⚡ 反應神速！但記得要仔細思考喔！\n"
        elif avg_answer_time <= 30:
            message += "⏱️ 思考速度剛好，很穩健的學習節奏！\n"
        else:
            message += "🐌 慢工出細活，但可以試著提高一點效率！\n"

        message += f"🕐 平均答題時間：{avg_answer_time:.1f}秒\n\n"

        # 個性化建議
        message += "💭 AI小老師的貼心建議：\n"

        if unanswered_count > total_questions * 0.3:
            message += "⏰ 有不少題目還沒完成，建議合理安排時間喔！\n"
        elif attitude_score < 60 and effectiveness_score < 70:
            message += "🎯 建議先提升專注力，可以試試番茄鐘學習法！\n"
        elif effectiveness_score < 70:
            message += "📖 多花點時間在PDF閱讀上，基礎打穩很重要！\n"
        elif avg_answer_time > 30:
            message += "⚡ 可以多做練習題來提升答題速度喔！\n"
        else:
            message += "🌈 你的學習狀態很棒！繼續保持這個節奏！\n"

        message += "\n🚀 加油！每一次學習都讓你更接近目標！"

        ai_advice = AIAdviceService.get_ai_advice(data)
        message += f"\n\n🤖 AI建議：{ai_advice}"

        return message


# 路由處理
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError as e:
        logger.error(f"Invalid signature: {str(e)}\n{traceback.format_exc()}")
        abort(400)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}\n{traceback.format_exc()}")
        abort(500)
    return "OK"


@app.route("/unity_notify", methods=["POST"])
def unity_notify():
    data = request.json

    if 'totalTime' in data:
        message = LearningReportGenerator.generate_learning_message(data)
    else:
        message = data.get("message", "遊戲開始啦！")

    result = MessageService.broadcast_message(message)
    return jsonify(result)


# 事件處理
@handler.default()
def default_handler(event):
    pass


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    UserManager.record_user_id(user_id)
    message_text = event.message.text.strip()
    logger.info(f"訊息: {message_text}")

    if message_text.lower() == "test":
        fake_data = LearningReportGenerator.generate_fake_data()
        test_message = LearningReportGenerator.generate_learning_message(fake_data)

        # 創建 Flex Message
        flex_bubble = create_learning_report_flex(test_message)

        configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text="🧪 測試學習報告", contents=flex_bubble)]
                    )
                )
            except Exception as e:
                logger.error(f"回覆測試訊息失敗: {e}")


@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    UserManager.record_user_id(user_id)
    logger.info(f"用戶加入好友: {user_id}")


def start_app():
    try:
        # 使用環境變數的 PORT，Render 會自動提供
        port = int(os.environ.get('PORT', 7000))
        app.run(host="0.0.0.0", port=port)
    finally:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.stop()
            if not loop.is_closed():
                loop.close()
        except RuntimeError as e:
            logger.error(f"Error cleaning up event loop: {str(e)}\n{traceback.format_exc()}")
        except Exception as e:
            logger.error(f"Unexpected error during cleanup: {str(e)}\n{traceback.format_exc()}")

def create_learning_report_flex(message):
    """
    將學習報告文字轉換為更漂亮的 Flex Message
    """
    lines = message.split('\n')

    # 解析數據
    data = parse_learning_data(lines)

    # 創建漂亮的 Flex Message
    return FlexBubble(
        size='giga',
        direction='ltr',
        header=create_header(),
        body=create_body(data),
    )


def parse_learning_data(lines):
    """解析學習報告數據"""
    data = {
        'sections': [],
        'ai_advice': '',
        'motivation': ''
    }

    current_section = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 解析章節
        if line.startswith('❶') or line.startswith('❷') or line.startswith('❸'):
            if current_section:
                data['sections'].append(current_section)

            # 解析標題、星星和分數
            import re
            section_match = re.match(r'(❶|❷|❸)([^⭐☆]+)', line)
            stars_match = re.search(r'([⭐☆]+)', line)
            score_match = re.search(r'\(([^)]+)\)', line)

            current_section = {
                'number': section_match.group(1) if section_match else '',
                'title': section_match.group(2).strip() if section_match else line,
                'stars': stars_match.group(1) if stars_match else '',
                'score': score_match.group(1) if score_match else '',
                'content': [],
                'stats': []
            }

        elif line.startswith('🤖 AI建議：'):
            data['ai_advice'] = line.replace('🤖 AI建議：', '').strip()

        elif line.startswith('🚀'):
            data['motivation'] = line

        elif current_section and (line.startswith('⏰') or line.startswith('✅') or
                                  line.startswith('❌') or line.startswith('⏸️') or
                                  line.startswith('🕐')):
            current_section['stats'].append(line)

        elif current_section and line:
            current_section['content'].append(line)

    if current_section:
        data['sections'].append(current_section)

    return data


def create_header():
    """創建漂亮的標題"""
    return FlexBox(
        layout='vertical',
        backgroundColor='#667eea',
        paddingAll='20px',
        contents=[
            FlexBox(
                layout='horizontal',
                contents=[
                    FlexText(
                        text="📊",
                        size='xxl',
                        color='#FFFFFF',
                        flex=1
                    ),
                    FlexBox(
                        layout='vertical',
                        flex=4,
                        contents=[
                            FlexText(
                                text="學習成果報告",
                                weight='bold',
                                size='xl',
                                color='#FFFFFF'
                            ),
                            FlexText(
                                text="Learning Report",
                                size='sm',
                                color='#E8EAFF',
                                margin='xs'
                            )
                        ]
                    )
                ]
            )
        ]
    )


def create_body(data):
    """創建主體內容"""
    contents = []

    # 添加各個章節
    for i, section in enumerate(data['sections']):
        if i > 0:
            contents.append(FlexSeparator(margin='lg'))

        contents.extend(create_modern_section(section, i))

    # 將 AI 建議移到這裡，移除激勵文字
    if data.get('ai_advice'):
        contents.append(FlexSeparator(margin='xl'))
        contents.append(create_ai_advice_box(data['ai_advice']))

    return FlexBox(
        layout='vertical',
        paddingAll='20px',
        backgroundColor='#f8f9ff',
        spacing='md',
        contents=contents
    )

def create_ai_advice_box(ai_advice):
    """創建 AI 建議框（在 body 內）"""
    return FlexBox(
        layout='vertical',
        backgroundColor='#1e293b',
        cornerRadius='lg',
        paddingAll='20px',
        contents=[
            FlexBox(
                layout='horizontal',
                contents=[
                    FlexText(
                        text="🤖",
                        size='lg',
                        color='#FFFFFF'
                    ),
                    FlexBox(
                        layout='vertical',
                        flex=5,
                        margin='sm',
                        contents=[
                            FlexText(
                                text="AI 專屬建議",
                                weight='bold',
                                size='md',
                                color='#FFFFFF'
                            ),
                            FlexText(
                                text=ai_advice,
                                size='sm',
                                color='#cbd5e1',
                                margin='xs',
                                wrap=True
                            )
                        ]
                    )
                ]
            )
        ]
    )

def create_modern_section(section, index):
    """創建現代化的章節設計"""
    # 顏色配置
    colors = [
        {'bg': '#4ade80', 'light': '#dcfce7', 'text': '#166534'},  # 綠色
        {'bg': '#fbbf24', 'light': '#fef3c7', 'text': '#92400e'},  # 黃色
        {'bg': '#f87171', 'light': '#fee2e2', 'text': '#991b1b'}  # 紅色
    ]

    color = colors[index % 3]

    contents = []

    # 章節標題卡片
    title_card = FlexBox(
        layout='vertical',
        backgroundColor=color['bg'],
        cornerRadius='lg',
        paddingAll='16px',
        contents=[
            FlexBox(
                layout='horizontal',
                contents=[
                    FlexText(
                        text=section['number'],
                        size='xl',
                        weight='bold',
                        color='#FFFFFF',
                        flex=1
                    ),
                    FlexBox(
                        layout='vertical',
                        flex=5,
                        contents=[
                            FlexText(
                                text=section['title'],
                                weight='bold',
                                size='lg',
                                color='#FFFFFF',
                                wrap=True
                            ),
                            FlexBox(
                                layout='horizontal',
                                margin='sm',
                                contents=[
                                    FlexText(
                                        text=section['stars'],
                                        size='md',
                                        color='#FFFFFF',
                                        flex=3
                                    ),
                                    FlexText(
                                        text=section['score'],
                                        size='md',
                                        weight='bold',
                                        color='#FFFFFF',
                                        align='end',
                                        flex=2
                                    )
                                ]
                            )
                        ]
                    )
                ]
            )
        ]
    )
    contents.append(title_card)

    # 內容卡片
    if section['content'] or section['stats']:
        content_items = []

        # 添加描述內容
        for content in section['content']:
            content_items.append(
                FlexText(
                    text=content,
                    size='sm',
                    color='#374151',
                    wrap=True,
                    margin='sm'
                )
            )

        # 添加統計數據
        if section['stats']:
            if content_items:
                content_items.append(FlexSeparator(margin='md'))

            stats_box = FlexBox(
                layout='vertical',
                backgroundColor='#ffffff',
                cornerRadius='md',
                paddingAll='12px',
                margin='sm',
                contents=[]
            )

            for stat in section['stats']:
                stats_box.contents.append(
                    FlexText(
                        text=stat,
                        size='sm',
                        color='#6b7280',
                        margin='xs'
                    )
                )

            content_items.append(stats_box)

        if content_items:
            content_card = FlexBox(
                layout='vertical',
                backgroundColor=color['light'],
                cornerRadius='md',
                paddingAll='16px',
                margin='sm',
                contents=content_items
            )
            contents.append(content_card)

    return contents


class AIAdviceService:
    @staticmethod
    def get_ai_advice(data):
        """
        使用 Gemini API 獲取學習建議
        """
        try:
            prompt = f"""根據以下學習數據，提供簡短的學習建議（限制50字以內）：
學習態度分數：{data['attitudeScore']}分
學習成效分數：{data['effectivenessScore']}分  
學習專心度分數：{data['concentrationScore']}分
答對題數：{data['correctCount']}題
答錯題數：{data['wrongCount']}題
平均答題時間：{data['avgAnswerTime']}秒

請提供具體且實用的建議。"""

            # 呼叫你現有的 generate_gemini_response 函數
            ai_reply = generate_gemini_response(prompt)
            # 如果回應包含錯誤訊息，返回預設建議
            if "錯誤" in ai_reply or "發生錯誤" in ai_reply:
                return "繼續保持學習熱忱！"

            return ai_reply.strip()

        except Exception as e:
            logger.error(f"獲取 AI 建議失敗: {e}")
            return "繼續保持學習熱忱！"


def generate_gemini_response(input_text):
    """
    使用 Gemini API 獲取回應
    """
    try:
        import google.generativeai as genai

        # 設定 API Key
        genai.configure(api_key=GEMINI_API_KEY)

        # 建立模型
        model = genai.GenerativeModel('gemini-2.0-flash')

        # 在用戶輸入中加入繁體字的指令
        enhanced_prompt = f"{input_text}\n\n請使用繁體中文回覆，不要使用簡體字。"

        # 生成回應
        response = model.generate_content(
            enhanced_prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                top_p=0.95,
                top_k=40,
                max_output_tokens=100,
            )
        )

        if response and response.text:
            return response.text.strip()
        else:
            return "繼續保持學習熱忱！"

    except Exception as e:
        logger.error(f"Gemini API 錯誤: {str(e)}")
        return "繼續保持學習熱忱！"

if __name__ == "__main__":
    start_app()
