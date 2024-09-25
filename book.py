#!/usr/bin/python3

import os
import time
import random
import base64
import datetime
import requests
import numpy as np
import cv2
import easyocr
from dotenv import load_dotenv

reader = easyocr.Reader(['en']) # this needs to run only once to load the model into memory

load_dotenv()

USERID = os.environ.get('USERID')
PASSWORD = os.environ.get('PASSWORD')
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'
TELEGRAM_BOT_BASE_URL = f'https://api.telegram.org/bot{os.environ.get('BOT_TOKEN')}/sendMessage'

class Slot:

    def __init__(self, id, slotIdEnc, bookingProgressEnc, startDateTime):
        self.id = id
        self.slotIdEnc = slotIdEnc
        self.bookingProgressEnc = bookingProgressEnc
        self.startDateTime = startDateTime
    
    def desirable(self, threshold_days=30):
        date_within_n_days = self.startDateTime < (datetime.datetime.now() + datetime.timedelta(days=threshold_days))
        date_before_limit = self.startDateTime.date().day < 32 and self.startDateTime.date().month == 5
        not_within_same_day = self.startDateTime.date() != datetime.datetime.today().date()
        after_1 = self.startDateTime.time().hour > 8
        mon = self.startDateTime.weekday() == 0 and self.startDateTime.time().hour < 18
        tue = self.startDateTime.weekday() == 1 and self.startDateTime.time().hour < 18
        wed = self.startDateTime.weekday() == 2 and self.startDateTime.time().hour > 14
        thu = self.startDateTime.weekday() == 3 and self.startDateTime.time().hour < 14
        fri = self.startDateTime.weekday() == 4 and self.startDateTime.time().hour < 18
        sat = self.startDateTime.weekday() != 5
        sun = self.startDateTime.weekday() != 6

        return date_within_n_days and date_before_limit and after_1 and (mon or tue or wed or thu or fri and sat and sun)

    def __repr__(self):
        return f"Slot {self.id} ({self.startDateTime:%a %d-%b %H:%M})"

def clean_slots(data):
    d = {}
    for slots in data.values():
        for slot in slots:
            date = datetime.datetime.strptime(slot['slotRefDate'][:10], "%Y-%m-%d")
            start_datetime = datetime.datetime.strptime(slot['slotRefDate'][:11] + slot['startTime'], "%Y-%m-%d %H:%M")
            slot_obj = Slot(slot['slotId'], slot['slotIdEnc'], slot['bookingProgressEnc'], start_datetime)
            if date not in d:
                d[date] = [slot_obj]
            else:
                d[date].append(slot_obj)
    return d

def find_wanted_slots(data):
    lst = []
    for date, slots in data.items():
        slots = list(filter(lambda x:x.desirable(), slots))
        lst.extend(slots)
        # if len(slots) > 1:
        #     lst.append(slots[1])
        # elif slots:
        #     lst.append(slots[0])
    return lst

def telegram_send(msg, redirect=False):
    print(msg)
    if redirect:
        requests.post(TELEGRAM_BOT_BASE_URL, json={"chat_id" : os.environ.get('CHAT_ID1'), "text" : msg})
    else:
        requests.post(TELEGRAM_BOT_BASE_URL, json={"chat_id" : os.environ.get('CHAT_ID1'), "text" : msg})

def telegram_send_list(msg, lst, redirect=False):
    s = msg
    for i in lst:
        if isinstance(i, list):
            for e in i:
                s += '\n'
                s += str(e)
        else:
            s += '\n'
            s += str(i)
    telegram_send(s, redirect)



LOGGED_IN = False
SHOW_BOOKINGS = True
telegram_send(f"bot started at {datetime.datetime.now()}.")

while True:
    if not LOGGED_IN:
        s = requests.Session()

        VERIFY_CODE_VALUE = ''
        while len(VERIFY_CODE_VALUE) != 4:
            captcha_r = s.post(r'https://booking.bbdc.sg/bbdc-back-service/api/auth/getLoginCaptchaImage', headers={'User-Agent': USER_AGENT})
            uri = captcha_r.json()['data']['image']
            encoded_data = uri.split(',')[1]
            nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
            cls = cv2.morphologyEx(img, cv2.MORPH_CLOSE, (3, 3))
            open = cv2.morphologyEx(cls, cv2.MORPH_OPEN, (3, 3))
            threshold = cv2.adaptiveThreshold(open, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 11, 4)
            result = reader.readtext(threshold, text_threshold=0.99999, allowlist='123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ', detail=0)
            if result:
                VERIFY_CODE_VALUE = result[0]
                CAPTCHA_TOKEN = captcha_r.json()['data']['captchaToken']
                VERIFY_CODE_ID = captcha_r.json()['data']['verifyCodeId']
        
        login_r = s.post(r'https://booking.bbdc.sg/bbdc-back-service/api/auth/login',
                         json={'captchaToken': CAPTCHA_TOKEN, 
                                'userId':USERID, 'userPass':PASSWORD,
                                'verifyCodeId': VERIFY_CODE_ID , 'verifyCodeValue': VERIFY_CODE_VALUE},
                         headers={'User-Agent': USER_AGENT})
        try:
            LOGIN_JWT = login_r.json()['data']['tokenContent']
        except KeyError:
            LOGGED_IN = False
            continue
        r1 = s.post(r'https://booking.bbdc.sg/bbdc-back-service/api/account/listAccountCourseType', headers={'Authorization': LOGIN_JWT, 'User-Agent': USER_AGENT})
        JSESHID = r1.json()['data']['activeCourseList'][0]['authToken']
        JSESHID_TIME = datetime.datetime.now()
        LOGGED_IN = True
        SHOW_BOOKINGS = True
        telegram_send("Login was necessary")
    if SHOW_BOOKINGS:
        SHOW_BOOKINGS = False
        try:
            balance_res = s.post(r'https://booking.bbdc.sg/bbdc-back-service/api/account/getUserProfile', headers={'Authorization': LOGIN_JWT, 'JSESSIONID': JSESHID, 'User-Agent': USER_AGENT})
            balance = balance_res.json()['data']['enrolDetail']['accountBal']
            booked_practical_list = s.post(r'https://booking.bbdc.sg/bbdc-back-service/api/booking/manage/listAllPracticalBooking', json = {"courseType":"3A"}, headers={'Authorization': LOGIN_JWT, 'JSESSIONID': JSESHID, 'User-Agent': USER_AGENT})
            practical_lst = list(map(lambda x: Slot(x['bookingId'], "","", datetime.datetime.strptime(x['slotRefDate'][:11] + x['startTime'], "%Y-%m-%d %H:%M")), booked_practical_list.json()['data']['theoryActiveBookingList']))
            booked_theory_list = s.post(r'https://booking.bbdc.sg/bbdc-back-service/api/booking/manage/listAllTheoryBooking', json = {"courseType":"3A"}, headers={'Authorization': LOGIN_JWT, 'JSESSIONID': JSESHID, 'User-Agent': USER_AGENT})
            theory_lst = list(map(lambda x: Slot(x['bookingId'], "","", datetime.datetime.strptime(x['slotRefDate'][:11] + x['startTime'], "%Y-%m-%d %H:%M")), booked_theory_list.json()['data']['theoryActiveBookingList']))
        except KeyError as err:
            LOGGED_IN = False
            continue
        
        telegram_send(f'Account balance is {balance}')
        telegram_send_list('Booked practical classes:', practical_lst)
        telegram_send_list('Booked theory classes:', theory_lst)

    if datetime.datetime.now() > JSESHID_TIME + datetime.timedelta(minutes=110):
        r1 = s.post(r'https://booking.bbdc.sg/bbdc-back-service/api/account/listAccountCourseType', headers={'Authorization': LOGIN_JWT, 'User-Agent': USER_AGENT})
        try:
            JSESHID = r1.json()['data']['activeCourseList'][0]['authToken']
            JSESHID_TIME = datetime.datetime.now()
        except KeyError as err:
            LOGGED_IN = False
            continue
        else:
            telegram_send('JSESHID refreshed succesfully', True)            
    
    booking_list_res = s.post(r'https://booking.bbdc.sg/bbdc-back-service/api/booking/c3practical/listC3PracticalSlotReleased',
                                json={"courseType":"3A","insInstructorId":"","stageSubDesc":"Practical Lesson","subVehicleType":None,"subStageSubNo":None},
                                headers={'Authorization': LOGIN_JWT, 'JSESSIONID': JSESHID, 'User-Agent': USER_AGENT})
    try:
        time.sleep(random.randint(60, 90))
        if booking_list_res.json()['data']["releasedSlotListGroupByDay"]:
            list_avail = booking_list_res.json()['data']['releasedSlotListGroupByDay']
            telegram_send_list('Available slots:', list(clean_slots(list_avail).values()), True)
            slots = find_wanted_slots(clean_slots(list_avail))
            if slots:
                telegram_send_list('Shortlisted slots:', slots, True)
            else:
                # print('None matched criteria')
                telegram_send('None matched criteria', True)
            for slot in slots:
                # telegram_send(f'Attempting to book slot {slot.id}')
                
                BOOK_VERIFY_CODE_VALUE = ''
                while len(BOOK_VERIFY_CODE_VALUE) != 4:
                    bookcaptcha_r = s.post(r'https://booking.bbdc.sg/bbdc-back-service/api/booking/manage/getCaptchaImage', headers={'Authorization': LOGIN_JWT, 'JSESSIONID': JSESHID, 'User-Agent': USER_AGENT})
                    uri = bookcaptcha_r.json()['data']['image']
                    encoded_data = uri.split(',')[1]
                    nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
                    cls = cv2.morphologyEx(img, cv2.MORPH_CLOSE, (3, 3))
                    open = cv2.morphologyEx(cls, cv2.MORPH_OPEN, (3, 3))
                    threshold = cv2.adaptiveThreshold(open, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 11, 4)
                    result = reader.readtext(threshold, text_threshold=0.9999999, allowlist='123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ', detail=0)
                    if result:
                        BOOK_VERIFY_CODE_VALUE = result[0]
                        BOOK_CAPTCHA_TOKEN = bookcaptcha_r.json()['data']['captchaToken']
                        BOOK_VERIFY_CODE_ID = bookcaptcha_r.json()['data']['verifyCodeId']

                

                # bookcaptcha_r = s.post(r'https://booking.bbdc.sg/bbdc-back-service/api/booking/manage/getCaptchaImage', headers={'Authorization': LOGIN_JWT, 'JSESSIONID': JSESHID, 'User-Agent': USER_AGENT})
                # CAPTCHA_TOKEN = bookcaptcha_r.json()['data']['captchaToken']
                # VERIFY_CODE_ID = bookcaptcha_r.json()['data']['verifyCodeId']
                # requests.post(f'https://api.telegram.org/bot{os.environ.get('BOT_TOKEN')}/sendPhoto', files={"photo": ("image.jpg", base64.b64decode(bookcaptcha_r.json()['data']['image'][22:]))}, data={"chat_id": '492461806'})
                
                # while not requests.post(f'https://api.telegram.org/bot{os.environ.get('BOT_TOKEN')}/getUpdates').json()['result']:
                #     time.sleep(1)
                # VERIFY_CODE_VALUE = requests.post(f'https://api.telegram.org/bot{os.environ.get('BOT_TOKEN')}/getUpdates').json()['result'][-1]['message']['text']
                # requests.post(f'https://api.telegram.org/bot{os.environ.get('BOT_TOKEN')}/getUpdates', json={'offset':requests.post(f'https://api.telegram.org/bot{os.environ.get('BOT_TOKEN')}/getUpdates').json()['result'][-1]['update_id']+1})


                book_slot_res = s.post(r'https://booking.bbdc.sg/bbdc-back-service/api/booking/c3practical/callBookC3PracticalSlot',
                                            json={"courseType":"3A","slotIdList":[slot.id],"encryptSlotList":[{"slotIdEnc":slot.slotIdEnc,"bookingProgressEnc":slot.bookingProgressEnc}],
                                            "verifyCodeId": BOOK_VERIFY_CODE_ID,
                                            "verifyCodeValue": BOOK_VERIFY_CODE_VALUE,
                                            "captchaToken": BOOK_CAPTCHA_TOKEN,
                                            "insInstructorId":"","subVehicleType":None,"instructorType":""},
                                            headers={'Authorization': LOGIN_JWT, 'JSESSIONID': JSESHID, 'User-Agent': USER_AGENT})
                if 'bookedPracticalSlotList' in book_slot_res.json()['data'] and book_slot_res.json()['data']['bookedPracticalSlotList']:
                    status = book_slot_res.json()['data']['bookedPracticalSlotList'][0]['success']
                    msg = book_slot_res.json()['data']['bookedPracticalSlotList'][0]['message']
                    if status:
                        SHOW_BOOKINGS = True
                        telegram_send(f'response for attempt to book slot {slot} is successful with message: {msg}')
                    else:
                        telegram_send(f'response for attempt to book slot {slot} is unsuccessful with message: {msg}', True)
                else:
                    telegram_send(f'response to book slot {slot.id} is {book_slot_res.json()}', True)
        else:
            print(f"No slots open")
    except KeyError as err:
        LOGGED_IN = False
        continue
    except Exception as err:
        telegram_send(str(err), True)
        telegram_send("unexpected error", True)
        LOGGED_IN = False
        continue
