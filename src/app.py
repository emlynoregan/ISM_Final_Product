import streamlit as st
import pandas as pd
import numpy as np
from PIL import Image
import cv2
import time
import openai
import os
from decouple import config
from streamlit_webrtc import webrtc_streamer, WebRtcMode, RTCConfiguration
import av
from streamlit_chat import message as st_message
import tensorflow as tf
import copy
import queue
import threading
import json


# Initialize OpenAI API
openai.organization = config("OPENAI_ORG_NAME")
openai.api_key = config("OPENAI_API_KEY")

RTC_CONFIGURATION = RTCConfiguration(
    {"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
)

#loading the pre-trained model file
model = tf.keras.models.load_model('final_model.h5')

class VideoProcessor:
    
    def __init__(self):
        self.emotion_dict_queue = queue.Queue()

    def recv(self, frame):
        processed_frames = []
        frame = frame.to_ndarray(format="bgr24")

        class_labels = ['Angry','Disgust','Fear','Happy','Neutral', 'Sad', 'Surprise']
        faceCascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
        #Detecting the faces
        faces = faceCascade.detectMultiScale(gray,1.1,4)
        for(x, y, w, h) in faces:

            #Drawing rectangle over the face area
            cv2.rectangle(frame, (x,y), (x+w, y+h), (0,255, 0), 2)
            face = gray[y:y + h, x:x + w]
            face = cv2.resize(face,(48,48))
            face = np.expand_dims(face,axis=0)
            face = face/255.0
            face = face.reshape(face.shape[0],48,48,1)

            # Predicting the emotion with the pre-trained model
            preds = model.predict(face, verbose = 0)[0]
            label = class_labels[preds.argmax()]
            font = cv2.FONT_HERSHEY_SIMPLEX
            cv2.putText(frame, label, (x,y), font, 1, (0,0,225), 2, cv2.LINE_4)
            
            frame_emotion_dict = {}
            for score, emotion in zip(preds, class_labels):
                frame_emotion_dict[emotion] = score
            
            # print(label)
            # print(frame_emotion_dict)

            self.emotion_dict_queue.put(frame_emotion_dict)

        # returning a frame of the live cam with it's corresponding emotion
        return processed_frames
        

# state management initialization
def initialize_state():
    if "num_prompts_user_sent" not in st.session_state:
        st.session_state.num_prompts_user_sent = 0

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    
    if 'emotion_history' not in st.session_state:
        st.session_state.emotion_history = []

    if "facial_emotion_dict" not in st.session_state:
        st.session_state.facial_emotion_dict = {'Angry': 0.0, 'Disgust': 0.0, 'Fear': 0.0, 'Happy': 0.0, 'Neutral': 0.0, 'Sad': 0.0, 'Surprise': 0.0}

    if "hacky_key_to_clear_input_on_submission" not in st.session_state:
        st.session_state.hacky_key_to_clear_input_on_submission = 1000


#TODO dropmenu for initial prompt options

    # initial_prompt = ("""I want you to act as a general human companion. 
    # You are an AI chatbot wired to a web application user interface that is recording and intepretting the user's emotions. The user will submit general comments to you.
    # The application will append the emotion data with the user's message in a dictionary format. 
    # Your job is to provide deep diving questions about this person and build a model of who they are in order to entertain them and provide them with companionship.
    # You are always meant to be positive and upbeat and to never let the conversation die so you must always ask a thought provoking question to keep the user engaged.
    # The conversation history will be provided in every prompt and you will be prepended with `'AI COMPANION':` and the user's responses will be labelled `'USER':` 
    # Provide only 1 completion of the response that the AI COMPANION should say:

    # """)

def dispatch_prompt():
    initial_prompt = ("""You are an AI chatbot on a website that is wired to a live webcam that is continuously summing the user's emotions of Angry, Disgust, Fear, Happy, Neutral, Sad and Surprise.
    Every frame calculates their relative emotions and adds it to the sum of emotions. 
    You will receive a series of prompts from said user and information about their emotion extracted from their face while they read your prompt.
    Your task is to make them feel good and happy. So take their feedback in consideration when constructing happy things to say.
    Here is their emotional status encoded in USER_EMOTIONS and message, respond to them to make them feel happy:
    
    """)

    user_prompt = st.session_state.input_text
    user_emotion = copy.deepcopy(st.session_state.facial_emotion_dict)
    
    if st.session_state.num_prompts_user_sent == 0:
        full_prompt = f"{initial_prompt} 'USER_EMOTIONS': {user_emotion}\n'USER': {user_prompt}\n"
        full_prompt += f"\n'AI COMPANION': "
    else:
        # construct the whole conversation.

        full_prompt = initial_prompt

        for i, msg in enumerate(st.session_state.chat_history):
            
            if msg.get("is_user"):
                full_prompt += f"'USER_EMOTIONS': {msg.get('user_emotion')} 'USER': {msg.get('message')}"
            else:
                full_prompt += f"'AI COMPANION': {msg.get('message')}"

        full_prompt += f"\n'USER_EMOTIONS': {user_emotion}"
        full_prompt += f"\n'USER': {user_prompt}"
        full_prompt += f"\n'AI COMPANION': "

    print(f"{st.session_state.num_prompts_user_sent=}")
    print(f"{full_prompt=}")
    
    response = openai.ChatCompletion.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "user", "content": full_prompt}
                        ]
                    )
    st.session_state.chat_history.append({'message':st.session_state.input_text, "is_user":True, 'user_emotion': user_emotion})
    st.session_state.chat_history.append({'message':response.choices[0].message.content, "is_user": False})
    st.session_state.num_prompts_user_sent +=1


def run_app():
    
    # Set page title
    st.set_page_config(page_title="Web Camera Emotion Detector and Chatbot")

    # Set page layout
    col1, col2 = st.columns([2, 1])


    initialize_state()

    # Add chatbox input/output display to page layout
    with col2:
        st.header("Live Emotion Detector")
        # Initialize video feed
        camera_stream = webrtc_streamer(
            key="WYH",
            mode=WebRtcMode.SENDRECV,
            rtc_configuration=RTC_CONFIGURATION,
            video_processor_factory=VideoProcessor,
            media_stream_constraints={"video": True, "audio": False},
            async_processing=True,
        )
        if camera_stream.state.playing:
            with col1:
                    st.header("AI ChatBot")

                    # start text input game.
                    st.text_input("Talk to ChatGPT Here!", key='input_text', on_change=dispatch_prompt)

                    # Display response
                    with st.container():
                        st.text('Chat History:')
                        if len(st.session_state.chat_history) != 0:
                        # reversed messages
                            for chat in st.session_state.chat_history[::-1]:
                                print(chat)
                                st_message(message=chat['message'], is_user=chat['is_user'])

            # current_emotion_label = st.empty()
            json_total_emotion_display = st.empty()
            # json_frame_emotion_display = st.empty()
            
            while True:
                if camera_stream.video_processor:
                    try:
                        frame_emotion_dict = camera_stream.video_processor.emotion_dict_queue.get(
                            timeout=1.0
                        )
                    except queue.Empty:
                        frame_emotion_dict = {'Angry': 0.0, 'Disgust': 0.0, 'Fear': 0.0, 'Happy': 0.0, 'Neutral': 0.0, 'Sad': 0.0, 'Surprise': 0.0}

                    # get a deep copy from facial_emotion_dict from state, += each of the values in the frame_emotion_dict, save it back to state.
                    current_facial_emotion_dict = copy.deepcopy(st.session_state.facial_emotion_dict)
                    for key, value in frame_emotion_dict.items():
                        current_facial_emotion_dict[key] += value
                    st.session_state.facial_emotion_dict = current_facial_emotion_dict

                    # current_emotion_label.text(f"Current Emotion\n{max(frame_emotion_dict, key=frame_emotion_dict.get)}: {max(frame_emotion_dict.values())}")

                    # json_frame_emotion_display.json(frame_emotion_dict)
                    json_total_emotion_display.json(current_facial_emotion_dict)

                else:
                    break

# Run the app
if __name__ == '__main__':
    run_app()