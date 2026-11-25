from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import pymysql.cursors
from tensorflow.keras.models import load_model
import numpy as np
from PIL import Image
import io
import base64
import os

from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
model = load_model('model_trained_14class_50epochs.hdf5')
app.secret_key = os.environ['FLASK_SECRET_KEY']

class_labels = [
    'apple',
    'baby_back_ribs',
    'chicken_wings',
    'dumplings',
    'french_fries',
    'fried_rice',
    'grape',
    'grilled_salmon',
    'onion_rings',
    'orange',
    'peking_duck',
    'pizza',
    'spring_rolls',
    'strawberry'
]

db = pymysql.connect(
    host="localhost",
    user="root",
    password=os.environ["DB_PASSWORD"],
    database="project",
    cursorclass=pymysql.cursors.DictCursor  # 使用字典游标，使得查询结果为字典形式
)

# 创建游标
cursor = db.cursor()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/sign_in')
def signIn():
    return render_template('register.html')


@app.route('/BMI')
def BMI():
    return render_template('BMI.html')


@app.route('/recongntion')
def recognition():
    return render_template('recognition.html')


# render the corresponding recipe page

@app.route('/recipes/<recipe_name>')
def render_recipe(recipe_name):
    page_path = f"recipes/{recipe_name}.html"
    return render_template(page_path)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Retrieve user from the database
        cursor.execute("SELECT * FROM user WHERE username = %s", (username,))
        user = cursor.fetchone()

        if user and check_password_hash(user['password'], password):
            session['username'] = username
            return redirect(url_for('index'))
        else:
            error_message = 'Invalid username or password. Please check your credentials.'
            return render_template('login.html', error=error_message)

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # 检查用户名是否已经存在
        cursor.execute("SELECT * FROM user WHERE username = %s", (username,))

        if (cursor.fetchone() is not None) & (len(password) < 6):
            return render_template('register.html',
                                   error="Username already taken.\n Password must be at least 6 characters long.",
                                   username=username, password=password)

        if cursor.fetchone():
            return render_template('register.html', error="Username already taken. Please choose a different username.",
                                   username=username, password=password)

        # 检查密码长度
        if len(password) < 6:
            return render_template('register.html', error="Password must be at least 6 characters long.",
                                   username=username, password=password)

        # 哈希密码
        hashed_password = generate_password_hash(password, method='sha256')

        # 插入新用户到数据库
        cursor.execute("INSERT INTO user (username, password) VALUES (%s, %s)", (username, hashed_password))
        db.commit()

        return redirect(url_for('login'))

    return render_template('register.html')


# check the session whether is in

def checkUserLoggedIn():
    if 'username' in session:
        return True
    else:
        return False


@app.route('/checkUserLoggedIn', methods=['GET'])
def check_user_logged_in():
    if checkUserLoggedIn():
        print(False)
        return jsonify({'loggedIn': True})
    else:
        print(True)
        return jsonify({'loggedIn': False})


@app.route('/saveUserData', methods=['POST'])
def save_user_data():
    if checkUserLoggedIn():
        data = request.json
        weight = data.get('weight')
        height = data.get('height')
        bmi = data.get('bmi')

        try:
            # update the height weight bmi
            query = "UPDATE user SET weight=%s, height=%s, bmi=%s WHERE username=%s"
            cursor.execute(query, (weight, height, bmi, session['username']))
            db.commit()
            return jsonify({'message': 'User data saved successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify({'error': 'User not logged in'}), 401


@app.route('/recommend', methods=['POST', 'GET'])
def recommend():
    if checkUserLoggedIn():
        # Retrieve the user's BMI from the session or the database
        query_bmi = "SELECT bmi FROM user WHERE username = %s"
        cursor.execute(query_bmi, (session['username'],))
        user_bmi = cursor.fetchone()  # Assuming there's only one user with this username
        # Determine BMI category based on user's BMI

        if user_bmi['bmi'] is None:
            return render_template('BMI.html')

        if user_bmi['bmi'] < 18.5:
            bmi_type = 1
        elif 18.5 <= user_bmi['bmi'] < 25:
            bmi_type = 2
        elif 25 <= user_bmi['bmi'] < 30:
            bmi_type = 3
        else:
            bmi_type = 4

        # Query the database to fetch meal options based on BMI type
        query_meal = """
            SELECT M.type, M.calories, M.content, M.nutrition, M.tips, M.fats, M.protein, M.fiber, M.carbs, S.swimming_time, S.walking_time, S.jogging_time, S.cycling_time
            FROM meals AS M
            INNER JOIN food_sport_times AS S ON M.meal_id = S.meal_id
            WHERE M.bmi_type = %s
        """

        cursor.execute(query_meal, (bmi_type,))

        meal_options = cursor.fetchall()

        return render_template('recommend.html', meal_options=meal_options, user_bmi=user_bmi)

    else:

        return render_template('login.html')


def preprocess_image(image):
    img = image.resize((299, 299))
    img = img.convert('RGB')
    img = np.array(img) / 255.0
    img = np.expand_dims(img, axis=0)
    return img


@app.route('/predict', methods=['POST'])
def predict():
    if 'file' not in request.files:
        return "No file part"

    file = request.files['file']
    if file.filename == '':
        return "No selected file"

    try:
        image = Image.open(io.BytesIO(file.read()))
        processed_image = preprocess_image(image)
        prediction = model.predict(processed_image)
        print('prediction', prediction)
        predicted_class = class_labels[np.argmax(prediction)]
        print('predicted_class', predicted_class)
        predicted_class_info = get_meal_info(predicted_class)
        # Reset file pointer position
        file.seek(0)
        img_str = base64.b64encode(file.read()).decode('utf-8')

        # 传递预测类别信息到 recipe.html
        return redirect(url_for('recipe', predicted_class=predicted_class, predicted_class_info=predicted_class_info))
    except Exception as e:
        return str(e)


@app.route('/recipe/<predicted_class>')
def recipe(predicted_class):
    # 查询数据库获取预测类别的信息
    predicted_class_info = get_meal_info(predicted_class)

    return render_template('recipe.html', predicted_class=predicted_class, predicted_class_info=predicted_class_info)


def get_meal_info(meal_name):
    # 连接数据库
    with db.cursor() as cursor:
        # 查询food表获取食物相关信息
        sql_food = "SELECT * FROM food WHERE name = %s"
        cursor.execute(sql_food, (meal_name,))
        food_info = cursor.fetchone()
        # print('food_info', food_info)
        # 查询food_desc表获取食物描述信息
        sql_desc = "SELECT * FROM food_desc WHERE meal_id = %s"
        cursor.execute(sql_desc, (food_info['id'],))
        desc_info = cursor.fetchone()

        # print('desc_info', desc_info)
        # 查询food_img表获取食物图片信息
        sql_img = "SELECT * FROM food_img WHERE food_id = %s"
        cursor.execute(sql_img, (food_info['id'],))
        img_info = cursor.fetchone()
        # print('img_info', img_info)
        # 查询food_sport_times表获取运动时间信息
        sql_sport = "SELECT * FROM food_sport_times WHERE food_id = %s"
        cursor.execute(sql_sport, (food_info['id'],))
        sport_info = cursor.fetchone()
        # print('sport_info', sport_info)
        # 整合所有信息到predicted_class_info字典中
        predicted_class_info = {
            'name': food_info['name'],
            'calories': food_info['calories'],
            'fats': food_info['fats'],
            'protein': food_info['protein'],
            'fiber': food_info['fiber'],
            'carbs': food_info['carbs'],
            'swimming_time': sport_info['swimming_time'],
            'walking_time': sport_info['walking_time'],
            'jogging_time': sport_info['jogging_time'],
            'cycling_time': sport_info['cycling_time'],
            'bg1': img_info['bg1'],
            'bg2': img_info['bg2'],
            'title': desc_info['title'],
            'sub_title': desc_info['sub_title'],
            'intro_top': desc_info['intro_top'],
            'intro_2': desc_info['intro_2'],
            'desc_bg1': desc_info['desc_bg1'],
            'intro': desc_info['intro'],
            'desc_bg2': desc_info['desc_bg2'],
            'desc': desc_info['desc'],
            'desc_bg3': desc_info['desc_bg3'],
            'nutrition': desc_info['nutrition']
        }
        print('predicted_class_info', predicted_class_info)
        return predicted_class_info


if __name__ == '__main__':
    app.run()
