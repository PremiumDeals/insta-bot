import os
import random
import requests
from flask import Flask, request, jsonify
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
    return "Instagram Bot is Live & Running!"

@app.route('/webhook', methods=['GET'])
def verify():
    # Meta Webhook Verification
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if token == VERIFY_TOKEN:
        return challenge
    return "Invalid Token", 403

@app.route('/webhook', methods=['POST'])
def handle_event():
    data = request.json
    
    # കമൻ്റ് വരുമ്പോൾ മാത്രം പ്രവർത്തിക്കുന്നു
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

    # 1. നെഗറ്റീവ് കീവേഡ് ചെക്ക്
    neg_words = supabase.table("negative_keywords").select("word").execute().data
    for word in neg_words:
        if word['word'].lower() in comment_text:
            return 

    # 2. കൂൾഡൗൺ ചെക്ക് (ഒരേ ആൾക്ക് വീണ്ടും മെസ്സേജ് പോകാതിരിക്കാൻ)
    recent_log = supabase.table("activity_logs").select("*").eq("user_id", user_id).eq("media_id", media_id).execute().data
    if recent_log:
        return

    # 3. ഗ്ലോബൽ സെറ്റിംഗ്സ്
    settings = supabase.table("settings").select("*").single().execute().data
    
    # 4. വീഡിയോയ്ക്കുള്ള പ്രത്യേക റൂൾ ഉണ്ടോ എന്ന് നോക്കുന്നു
    rule = supabase.table("media_rules").select("*").eq("media_id", media_id).eq("active", True).execute().data
    rule_data = rule[0] if rule else None
    
    if rule_data or settings.get('universal_reply'):
        send_dm(user_id, rule_data)
        post_public_reply(comment_id)
        
        # ലോഗ് സേവ് ചെയ്യുന്നു
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
      
