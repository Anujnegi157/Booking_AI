import streamlit as st
import requests
import openai
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import re

# Function to extract information from the transcript using OpenAI GPT-4
def connect_db(user_details):
    uri = st.secrets["api_keys"]["url"]
    client = MongoClient(uri, server_api=ServerApi('1'))
    db = client['UserDb']
    collection = db['UserCollection']
    result = collection.insert_one(user_details)
    
    try:
        client.admin.command('ping')
        print("Pinged your deployment. You successfully connected to MongoDB!")
    except Exception as e:
        print("An error occurred while connecting to MongoDB:", e)
    
    return result.inserted_id

def extract_info(prompt, transcript_text):
    try:
        openai.api_key = st.secrets["api_keys"]["api_key"]
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt.format(transcript_text=transcript_text)}
            ],
            max_tokens=100
        )
        info = response.choices[0].message['content'].strip()
        return info
    except Exception as e:
        return f"An error occurred: {e}"

def get_time_mail(call_id):
    try:
        url = f"https://api.bland.ai/v1/calls/{call_id}"
        headers = {
            "authorization": st.secrets["api_keys"]["bland_ai"]
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if 'transcripts' not in data:
            return "Transcript not found."

        transcripts = data['transcripts']
        transcript_text = "\n".join([t['text'] for t in transcripts])
        
        date_prompt = "Extract the appointment only date from the following transcript and don't give any other text: {transcript_text}"
        time_prompt = "Extract the appointment only time not date from the following transcript and don't give any other text: {transcript_text}"
        
        appointment_date = extract_info(date_prompt, transcript_text)
        appointment_time = extract_info(time_prompt, transcript_text)
        
        return {
            "date": appointment_date,
            "time": appointment_time,
        }
    except requests.exceptions.RequestException as e:
        return f"An error occurred: {e}"
    except KeyError as e:
        return f"Missing expected data in response: {e}"

def send_to_webhook(data):
    print("working")
    webhook_url = "https://connect.pabbly.com/workflow/sendwebhookdata/IjU3NjUwNTY0MDYzNTA0MzQ1MjY5NTUzYzUxMzEi_pc"
    if "_id" in data and isinstance(data["_id"], ObjectId):
        data["_id"] = str(data["_id"])
    response = requests.post(webhook_url, json=data)
    if response.status_code == 200:
        print('Data sent to webhook successfully!')
    else:
        print('Failed to send data to webhook.')

def remove_ordinal_suffix(date_str):
    return re.sub(r'(\d)(st|nd|rd|th)', r'\1', date_str)

def convert_to_iso_format(date_str, time_str):
    date_str = remove_ordinal_suffix(date_str)
    datetime_str = f"{date_str} {time_str}"
    
    # Define possible date and time formats
    date_formats = ["%B %d, %Y", "%b %d, %Y", "%d %B, %Y", "%d %b, %Y", "%d %B %Y", "%d %b %Y"]
    time_formats = ["%I:%M %p", "%I %p", "%H:%M", "%H:%M:%S"]
    
    for date_format in date_formats:
        for time_format in time_formats:
            try:
                datetime_obj = datetime.strptime(datetime_str, f"{date_format} {time_format}")
                return datetime_obj.isoformat()
            except ValueError:
                continue
    raise ValueError(f"time data '{datetime_str}' does not match any of the expected formats")


# Function to request a demo call
def request_demo(customer_name, phone_number, actor_id, calling_agent_name, email):
    api_key = st.secrets["api_keys"]["bland_ai"]
    
    prompt = f"""
BACKGROUND INFO:
    You are {calling_agent_name}, an AI scheduling assistant for Geekster. Your role is to help callers schedule appointments by collecting their name, email address, and preferred appointment time.

Greeting the Caller

Friendly Introduction:
"Hello, good [morning/afternoon/evening]! My name is {calling_agent_name}, and I’m calling from Geekster. Am I speaking with {customer_name}?"

Confirming Identity and Purpose:
"I noticed you recently expressed interest in scheduling an appointment with us. I’d like to assist you in setting this up. Could you please provide me with your preferred appointment date and time?"

Collecting Appointment Details:
"Please provide the exact date and time you would like for your appointment. The date should be in the format DD-MM-YYYY (e.g., 15-08-2024 for August 15, 2024), and the time should be in 12-hour AM/PM format (e.g., 2:00 PM for 2 PM, 9:30 AM for 9:30 AM)."

Verifying the Details:
"To confirm, you would like to schedule an appointment on {{Specific Date}} at {{Specific Time}}, and your email address is {email}. Is that correct?"

Ending the Call:
"Great! I have scheduled your appointment for {{Specific Date}} at {{Specific Time}}. You will receive a confirmation email shortly. Thank you for your time, and have a wonderful day!"

If the Caller Wants to Change or Cancel:
"If you need to change or cancel your appointment, please contact us at [Contact Information]. Thank you!"
    """
    
    data = {
        "phone_number": phone_number,
        "task": prompt,
        "voice_id": actor_id,
        "reduce_latency": True,
    }
    
    try:
        response = requests.post(
            "https://api.bland.ai/call",
            json=data,
            headers={
                "authorization": st.secrets["api_keys"]["bland_ai"],
                "Content-Type": "application/json",
            },
        )
        response_data = response.json()
        print(response_data)
        if response.status_code == 200 and response_data.get("status"):
            call_id = response_data.get("call_id")
            while True:
                try:
                    url = f"https://api.bland.ai/v1/calls/{call_id}"
                    headers = {"authorization": api_key}
                    response = requests.get(url, headers=headers)
                    response_data1 = response.json()
                    if response_data1.get("status") == "completed":
                        break
                except Exception as e:
                    return f"An error occurred: {e}"
            time_date_email = get_time_mail(call_id)
            print(time_date_email)
            time_date_email['email'] = email  # Add email to the time_date_email dictionary
            inserted_id = connect_db(time_date_email)
            time_date_email["_id"] = inserted_id
            start_datetime_iso = convert_to_iso_format(time_date_email["date"], time_date_email["time"])
            end_datetime_iso = (datetime.fromisoformat(start_datetime_iso) + timedelta(hours=1)).isoformat()
            event_details = {
                "calendar": "Your Calendar Name",
                "title": "Appointment with Client",
                "description": "Discussion about the project requirements and timelines.",
                "location": "India",
                "start_date_time": start_datetime_iso,
                "end_date_time": end_datetime_iso,
                "time_zone": "Asia/Kolkata",
                "visibility": "public",
                "guests": email,
                "reminders_method": "email",
                "minutes_before_reminders": 30,
                "color": 5,
                "show_me_as_free_or_busy": "busy",
                "guests_can_modify_event": False,
                "event_recurrence_rule": "RRULE:FREQ=DAILY;INTERVAL=1;COUNT=1",
                "add_conferencing": "yes"
                }
            send_to_webhook(event_details)
            print(time_date_email)
            return time_date_email
        else:
            return {"message": "Error dispatching phone call", "status": "error"}

    except Exception as e:
        return {"message": f"Error: {e}", "status": "error"}

# Actor dictionary
actor_dict = {
    "Indian Male": "4ca175b7-3d84-45d2-83d3-c97f0839815c",
    "American Male": "2c01ebe7-45d4-4b58-9686-617fa283dd8e",
    "American Female": "13843c96-ab9e-4938-baf3-ad53fcee541d"
}

# Streamlit app layout
st.title("Booking Service with AI")

customer_name = st.text_input("What's your name?", "Saurabh")
phone_number = st.text_input("What's your phone number?", "+91 ")
actor = st.selectbox("Select voice agent you are expecting", list(actor_dict.keys()))
actor_id = actor_dict[actor]
calling_agent_name = st.text_input("Calling Agent Name?", "Anuj")
email = st.text_input("Please enter your email")

if st.button("Talk to VirtualVoice"):
    response = request_demo(customer_name, phone_number, actor_id, calling_agent_name, email)
    st.write("API Response:")
    st.write(response)

# To run the Streamlit app, save this script and use the command: streamlit run script.py
