# Student Placement Prediction Web App

## Overview
This is a Flask-based web application that predicts whether a student is likely to be placed in a job based on input features such as age, gender, academic stream, internship experience, hostel status, CGPA, and backlog history. The application uses a Decision Tree Classifier trained on dataset features to make predictions.

## Features
- **Input Form**: Allows users to enter student details, including name, age, gender, stream, internship count, hostel status, CGPA, and backlogs.
- **Eligibility Check**: Uses predefined rules for age, CGPA, and backlogs before the ML prediction.
- **Prediction**: Predicts placement eligibility using a trained Decision Tree Classifier.
- **Web Interface**: Built with Flask and rendered using Jinja2 templates.
- **History**: Saves predictions per logged-in user and displays recent results on the dashboard.

## Requirements
To run this project, install the following Python packages:
- Flask
- pandas
- numpy
- scikit-learn
- Werkzeug

Install dependencies with:
```bash
pip install -r requirements.txt
```

## Project Structure
- **app.py**: Flask application with registration, login, dashboard, prediction form, and result pages.
- **templates/**: HTML templates for the web UI.
- **static/css/style.css**: Custom dark-theme styling.
- **collegePlacement_cleanData.csv**: Dataset used to train the model.
- **requirements.txt**: Python package requirements.

## Running Locally
1. Install dependencies:
```bash
pip install -r requirements.txt
```
2. Start the app:
```bash
python app.py
```
3. Open a browser at `http://127.0.0.1:5000`

## Notes
- The app supports user registration and login.
- The model trains once at startup and is reused for predictions.
- Replace `FLASK_SECRET_KEY` with a secure environment value in deployment.

## How It Works
1. The app loads the dataset from `collegePlacement_cleanData.csv`.
2. It trains a Decision Tree Classifier on features like age, gender, stream, internships, hostel, CGPA, and backlog history.
3. Users log in and submit student details on the prediction form.
4. The app checks eligibility, runs the model, and shows if the candidate is "Eligible for placements" or "Not eligible for placements." 

## Usage
1. **Clone the repository**:
   ```bash
git clone https://github.com/abhishek-bhat2005/Smart-Placement-Predictions.git
cd Smart-Placement-Predictions
```
2. **Install dependencies**:
   ```bash
pip install -r requirements.txt
```
3. **Run the application**:
   ```bash
python app.py
```
4. **Open the web app**:
   `http://127.0.0.1:5000`

## Notes
- Ensure the dataset file `collegePlacement_cleanData.csv` is present in the project directory.
- The web app uses a local SQLite database for users and predictions.
- For deployment, consider using environment variables for `FLASK_SECRET_KEY` and database configuration.

## License
This project is licensed under the MIT License.

