import os
import random
import requests
from flask import Flask, request, jsonify, render_template
from supabase import create_client, Client

app = Flask(__name__)

# Environment Variables (Vercel-ൽ നിന്ന് എടുക്കുന്നത്)
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
IG_TOKEN = os.environ.get("IG_ACCESS_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")

supabase: Client = create_client(URL, KEY)

@app.route('/')
def home():
    return render_template('index.html', supabase_url=URL, supabase_key=KEY)

@app.route('/api/media', methods=['GET'])
def fetch_media():
    if not IG_TOKEN:
        return jsonify({"error": "Missing Instagram access token."}), 500

    try:
        # Step 1: Get Facebook Page ID(s)
        accounts_url = f"https://graph.facebook.com/v19.0/me/accounts?access_token={IG_TOKEN}"
        accounts_response = requests.get(accounts_url, timeout=12)
        accounts_response.raise_for_status()
        accounts_data = accounts_response.json()

        if accounts_data.get("error"):
            error_msg = accounts_data["error"].get("message", "Failed to fetch accounts.")
            print(f"[Error] Step 1 - Accounts API: {error_msg}")
            return jsonify({"error": error_msg}), 502

        page_id = None
        if accounts_data.get("data") and len(accounts_data["data"]) > 0:
            page_id = accounts_data["data"][0].get("id")

        if not page_id:
            print("[Error] Step 1 - No Facebook Page ID found in response.")
            return jsonify({"error": "No connected Facebook Page found."}), 404

        print(f"[Step 1] Facebook Page ID: {page_id}")

        # Step 2: Get Instagram Business Account ID
        page_url = (
            f"https://graph.facebook.com/v19.0/{page_id}"
            f"?fields=instagram_business_account&access_token={IG_TOKEN}"
        )
        page_response = requests.get(page_url, timeout=12)
        page_response.raise_for_status()
        page_data = page_response.json()

        if page_data.get("error"):
            error_msg = page_data["error"].get("message", "Failed to fetch page details.")
            print(f"[Error] Step 2 - Page Details API: {error_msg}")
            return jsonify({"error": error_msg}), 502

        ig_account_id = None
        if page_data.get("instagram_business_account"):
            ig_account_id = page_data["instagram_business_account"].get("id")

        if not ig_account_id:
            print("[Error] Step 2 - No Instagram Business Account ID found. Is this a connected Instagram Page?")
            return jsonify({"error": "No Instagram Business Account connected to this page."}), 404

        print(f"[Step 2] Instagram Business Account ID: {ig_account_id}")

        # Step 3: Fetch media from Instagram Business Account
        media_url = (
            f"https://graph.facebook.com/v19.0/{ig_account_id}/media"
            f"?fields=id,caption,media_url,thumbnail_url,media_type,permalink"
            f"&access_token={IG_TOKEN}"
        )
        media_response = requests.get(media_url, timeout=12)
        media_response.raise_for_status()
        media_data = media_response.json()

        if media_data.get("error"):
            error_msg = media_data["error"].get("message", "Failed to fetch media.")
            print(f"[Error] Step 3 - Media API: {error_msg}")
            return jsonify({"error": error_msg}), 502

        print(f"[Step 3] Successfully fetched {len(media_data.get('data', []))} posts.")
        return jsonify(media_data), 200

    except requests.exceptions.RequestException as exc:
        print(f"[Error] HTTP Request Failed: {str(exc)}")
        return jsonify({"error": "Failed to fetch Instagram media.", "details": str(exc)}), 502
    except KeyError as exc:
        print(f"[Error] Missing key in API response: {str(exc)}")
        return jsonify({"error": "Unexpected API response format.", "details": str(exc)}), 502
    except Exception as exc:
        print(f"[Error] Internal server error: {str(exc)}")
        return jsonify({"error": "Internal server error.", "details": str(exc)}), 500

@app.route('/webhook', methods=['GET'])
def verify():
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if token == VERIFY_TOKEN:
        return challenge
    return "Invalid Token", 403

@app.route('/webhook', methods=['POST'])
def handle_event():
    data = request.json

    if 'entry' in data:
        for entry in data['entry']:
            for change in entry.get('changes', []):
                if change.get('field') == 'comments':
                    comment_data = change['value']
                    process_comment(comment_data)

    return jsonify({"status": "success"}), 200


def process_comment(comment):
    comment_id = comment.get('id')
    comment_text = comment.get('text', '').lower()
    media_id = comment.get('media', {}).get('id')
    user_id = comment.get('from', {}).get('id')
    username = comment.get('from', {}).get('username')

    neg_words = supabase.table("negative_keywords").select("word").execute().data or []
    for word in neg_words:
        if word['word'].lower() in comment_text:
            return

    recent_log = supabase.table("activity_logs").select("*").eq("user_id", user_id).eq("media_id", media_id).execute().data
    if recent_log:
        return

    settings = supabase.table("settings").select("*").single().execute().data or {}
    rule = supabase.table("media_rules").select("*").eq("media_id", media_id).eq("active", True).execute().data
    rule_data = rule[0] if rule else None

    if rule_data or settings.get('universal_reply'):
        send_dm(user_id, rule_data)
        post_public_reply(comment_id)

        supabase.table("activity_logs").insert({
            "user_id": user_id,
            "username": username,
            "comment_text": comment_text,
            "media_id": media_id,
            "action_type": "DM_SENT"
        }).execute()


def post_public_reply(comment_id):
    replies = supabase.table("public_comments").select("comment_text").execute().data
    if replies:
        random_reply = random.choice(replies)['comment_text']
        url = f"https://graph.facebook.com/v19.0/{comment_id}/replies"
        payload = {"message": random_reply, "access_token": IG_TOKEN}
        requests.post(url, data=payload)


def send_dm(user_id, rule):
    url = f"https://graph.facebook.com/v19.0/me/messages"
    message_text = rule.get('dm_text') if rule else "ഹലോ! കൂടുതൽ വിവരങ്ങൾക്കായി ലിങ്കിൽ ക്ലിക്ക് ചെയ്യുക."

    payload = {
        "recipient": {"id": user_id},
        "message": {"text": message_text},
        "access_token": IG_TOKEN
    }
    requests.post(url, json=payload)

if __name__ == '__main__':
    app.run(debug=True)
    
