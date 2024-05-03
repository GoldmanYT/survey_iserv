import sqlite3
import logging
import os
import json
from config import BOT_TOKEN
from consts import *
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler, filters)

# logging.basicConfig(
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG
# )
#
# logger = logging.getLogger(__name__)
conn = sqlite3.connect('my_database.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, status TEXT, city TEXT)''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS
records(
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    survey_id INTEGER,
    answers TEXT
)''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS
surveys(
    id INTEGER PRIMARY KEY,
    file_path TEXT
)''')


def update_bd():
    cursor.execute('''
    DELETE FROM surveys 
    ''')
    values = []
    for current, folders, files in os.walk('surveys/'):
        for file in files:
            values.append(current + file)
    cursor.execute(f'''
    INSERT INTO surveys (file_path)
    VALUES {', '.join(f'("{file_name}")' for file_name in values)}
    ''')
    conn.commit()


update_bd()
conn.commit()
with open('russian-cities.json', encoding='utf-8-sig') as file:
    cities = [info['name'].lower() for info in json.load(file)]
cities.extend(['луганск', 'донбасс', 'херсон'])


async def start(update, context) -> None:
    user_id = update.effective_user.id

    request_users = cursor.execute('SELECT user_id FROM users').fetchall()
    if (user_id,) not in request_users:
        keyboard = [['Да', 'Нет']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text('Хотите зарегистрироваться?', reply_markup=reply_markup)
        context.user_data['step'] = 1
        return
    else:
        keyboard = [['Список опросов']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text('Вы уже зарегистрированы', reply_markup=reply_markup)
        return


async def get_admin(update, context) -> None:
    user_id = update.effective_user.id
    cursor.execute('UPDATE users SET status = "admin"'
                   'WHERE user_id = ?', (user_id, ))
    conn.commit()
    await update.message.reply_text('Вы уже смешарик')


async def stats_request(update, context):
    user_id = update.effective_user.id
    status = cursor.execute('''SELECT status FROM users
                                    WHERE user_id = ?''', (user_id,)).fetchone()[0]
    if context.user_data.get('step') == ADMIN_MODE and update.message.text not in ('>', '<') and\
            status != "user":
        if update.message.text == 'Выйти':
            context.user_data['step'] = SURVEY_LIST_STEP
            keyboard = [['Список опросов']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text("Вы вышли из админки",
                                            reply_markup=reply_markup)
            return
        title = update.message.text[update.message.text.find('.') + 2:]
        file_paths = get_available_surveys(-1)
        matching_file_paths = []
        for file_path in file_paths:
            with open(file_path, encoding='utf-8') as json_file:
                data = json.load(json_file)
                if data['title'] == title:
                    matching_file_paths.append(file_path)
                    questions = data['questions']
                    break
        file_path = min(matching_file_paths)
        survey_id = cursor.execute('''SELECT id FROM surveys
                                                WHERE file_path = ?''', (file_path,)).fetchone()[0]
        stats = cursor.execute('''SELECT answers FROM records
                                          WHERE survey_id = ?''', (survey_id,)).fetchall()
        questions_text = [elem['text'] for elem in questions]
        questions_answer = [elem['answers'] for elem in questions]
        answers_stats = [[0 for _ in range(len(questions_answer[i]))] for i in range(len(questions_text))]
        for i in range(len(stats)):
            now_answer = stats[i][0].split(';;')
            for j, (x, answers) in enumerate(zip(now_answer, questions_answer)):
                index_answer = answers.index(x)
                answers_stats[j][index_answer] += 1

        stats_str = f"Статистика по опросу: \"{data['title']}\"\n" \
                    f"Количество участников: {len(stats)}\n\n"
        for i in range(len(questions_text)):
            stats_str += f"Вопрос №{i+1}: {questions_text[i]}\n"
            for quest in range(len(questions_answer[i])):
                stats_str += f"\"{questions_answer[i][quest]}\": {answers_stats[i][quest]}\n"
            stats_str += "\n"

        await update.message.reply_text(stats_str)
    if status != "user":
        if update.message.text == '>':
            context.user_data['page'] += 1
        elif update.message.text == '<':
            context.user_data['page'] -= 1
        else:
            context.user_data['page'] = 0
        context.user_data['step'] = ADMIN_MODE
        titles = []
        file_paths = get_available_surveys(-1)
        context.user_data['page'] %= (len(file_paths) + SURVEY_COUNT_ON_PAGE - 1) // SURVEY_COUNT_ON_PAGE
        for file_path in file_paths:
            with open(file_path, encoding='utf-8') as json_file:
                data = json.load(json_file)
                titles.append(data['title'])
        keyboard = []
        page = context.user_data['page']
        lst = list(enumerate(titles, 1))
        for i, title in lst[page * SURVEY_COUNT_ON_PAGE:(page + 1) * SURVEY_COUNT_ON_PAGE]:
            keyboard.append([f'{i}. {title}'])
        keyboard.append(['<', 'Выйти', '>'])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Выберите опрос, по которому желаете узнать статистику.",
                                        reply_markup=reply_markup)


async def handle_poll(update, context):
    user_id = update.effective_user.id
    if context.user_data.get('step') is not None:
        reply_markup = ReplyKeyboardRemove()
        if context.user_data.get('step') == REGISTRATION_STEP and update.message.text == "Да":
            await update.message.reply_text("Пожалуйста, укажите город. Пример: Санкт-Петербург.",
                                            reply_markup=reply_markup)
            context.user_data['step'] = END_REGISTRATION_STEP
        elif context.user_data.get('step') == REGISTRATION_STEP and update.message.text == "Нет":
            await update.message.reply_text(
                "Вы отказались от регистрации. Если измените своё решение, то нажмите /start",
                reply_markup=reply_markup)
            context.user_data.clear()
            return
        elif context.user_data.get('step') == END_REGISTRATION_STEP:
            if update.message.text.lower() in cities:
                keyboard = [['Список опросов']]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                context.user_data['city'] = update.message.text
                cursor.execute("INSERT INTO users (user_id, status, city) VALUES (?, ?, ?)",
                               (int(user_id), "user", context.user_data['city']))
                conn.commit()
                context.user_data.clear()
                await update.message.reply_text("Спасибо за регистрацию!", reply_markup=reply_markup)
                context.user_data['step'] = SURVEY_LIST_STEP
                return
            else:
                await update.message.reply_text("Извините, но мы не нашли указанный вами город.\n"
                                                "Попробуйте еще раз.")
    if update.message.text in ("Список опросов", '>', '<') and \
            context.user_data.get('step') != ADMIN_MODE:
        update_bd()
        filtered_file_paths = get_available_surveys(user_id)
        keyboard = []
        titles = []
        for file_path in filtered_file_paths:
            with open(file_path, encoding='utf-8') as json_file:
                data = json.load(json_file)
                titles.append(data['title'])
        context.user_data['available_surveys'] = titles
        n_pages = (len(titles) + SURVEY_COUNT_ON_PAGE - 1) // SURVEY_COUNT_ON_PAGE
        if update.message.text == 'Список опросов':
            context.user_data['page'] = 0
        elif update.message.text == '>':
            context.user_data['page'] += 1
            context.user_data['page'] %= n_pages
        elif update.message.text == '<':
            context.user_data['page'] -= 1
            context.user_data['page'] %= n_pages
        page = context.user_data['page']
        lst = list(enumerate(titles, 1))
        for i, title in lst[page * SURVEY_COUNT_ON_PAGE:(page + 1) * SURVEY_COUNT_ON_PAGE]:
            keyboard.append([f'{i}. {title}'])
        if n_pages > 1:
            keyboard.append(['<', '>'])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Список опросов", reply_markup=reply_markup)
        return
    elif context.user_data.get('available_surveys') is not None and \
            (update.message.text[update.message.text.find('.') + 2:] in
             context.user_data['available_surveys']) and \
            context.user_data.get('step') != ADMIN_MODE:
        update_text = update.message.text[update.message.text.find('.') + 2:]
        context.user_data['step'] = IN_SURVEY
        file_paths = get_available_surveys(user_id)
        matching_file_paths = []
        for file_path in file_paths:
            with open(file_path, encoding='utf-8') as json_file:
                data = json.load(json_file)
                if data['title'] == update_text:
                    matching_file_paths.append(file_path)
        context.user_data['current_survey_fp'] = min(matching_file_paths)
        context.user_data['answers'] = []
        context.user_data['current_question'] = 0
        current_sid = cursor.execute('''SELECT id FROM surveys
                                        WHERE file_path = ?''', (min(matching_file_paths),)).fetchone()

        context.user_data['current_survey_id'] = current_sid[0]
    if context.user_data.get('step') == IN_SURVEY:
        file_path = context.user_data['current_survey_fp']
        with open(file_path, encoding='utf-8') as json_file:
            data = json.load(json_file)
            questions = data['questions']
        n_question = context.user_data['current_question']
        answer = update.message.text
        if 0 <= n_question < len(questions) and answer in questions[n_question]['answers']:
            context.user_data['answers'].append(answer)
        if 0 <= n_question < len(questions) and answer in questions[n_question]['answers']:
            context.user_data['current_question'] += 1
        n_question = context.user_data['current_question']
        if n_question >= len(questions):
            cursor.execute('''INSERT INTO records(user_id, survey_id, answers) VALUES(?, ?, ?)''',
                           (user_id, context.user_data.get('current_survey_id'),
                            ';;'.join(context.user_data['answers'])))
            conn.commit()
            text = 'Вы прошли опрос!'
            context.user_data['step'] = SURVEY_LIST_STEP
            keyboard = [['Список опросов']]
        else:
            text = questions[n_question]['text']
            keyboard = []
            lst = questions[n_question]['answers']
            for i in range((len(lst) + 1) // 2):
                keyboard.append(lst[i * 2:(i + 1) * 2])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(text, reply_markup=reply_markup)
        return
    elif context.user_data.get('step') == ADMIN_MODE:
        await stats_request(update, context)


def get_available_surveys(user_id):
    file_paths = cursor.execute('''SELECT id, file_path FROM surveys''').fetchall()
    survey_ids = [i[0] for i in cursor.execute(f'''SELECT survey_id FROM records
                                                   WHERE user_id = {user_id}''').fetchall()]
    filtered_file_paths = [file_path for survey_id, file_path in file_paths
                           if survey_id not in survey_ids]
    return filtered_file_paths


def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('stats', stats_request))
    application.add_handler(CommandHandler('iserv', get_admin))
    application.add_handler(MessageHandler(filters.TEXT, handle_poll))
    application.run_polling()


if __name__ == '__main__':
    main()
