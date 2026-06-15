# GPTictionary Web

GPTictionary Web is a personal English learning platform built with FastAPI.

Originally started as a Telegram-based vocabulary bot, the project has evolved into a full web application that helps users save vocabulary, search expressions, review learned words, ask English questions, and practice through quizzes.

## Features

### Vocabulary Search

* Search English words and expressions
* Automatically generates:

  * Korean definition
  * Example sentence
  * Synonyms
  * Usage notes
* New vocabulary is automatically saved to the database

### Vocabulary Notebook

* View all saved vocabulary
* Search and sort words
* Track learning progress

### English Question Notebook

* Ask questions about English expressions
* Answers are generated using OpenAI
* Question history is stored in Qdrant Vector Database
* Similar questions can be reused without calling OpenAI again

### Quiz System

* Fill-in-the-blank vocabulary quizzes
* Automatic scoring
* Tracks:

  * Correct answers
  * Wrong answers
  * Priority score
  * Memorization count
* Generates quizzes from saved vocabulary

### Learning Statistics

* Total vocabulary count
* Most missed words
* Most memorized words
* Learning dashboard

## Tech Stack

### Backend

* FastAPI
* SQLAlchemy
* Jinja2
* PyMySQL

### AI

* OpenAI GPT-4o-mini
* OpenAI Embeddings

### Database

* MariaDB
* Qdrant Vector Database

### Deployment

* Docker
* Synology NAS
* Nginx Reverse Proxy (planned)

## Architecture

User
↓
FastAPI Web
↓
MariaDB (Vocabulary Storage)
↓
OpenAI API

User Questions
↓
Embedding
↓
Qdrant Vector DB
↓
Similar Question Search

## Project Structure

backend/
├── api/
├── crud/
├── db/
├── models/
├── schemas/
├── services/
├── static/
├── templates/
└── main.py

## Future Plans

* Spaced Repetition System (SRS)
* AI-generated quiz explanations
* Review mode
* User accounts
* Mobile-friendly UI
* Domain deployment (gptictionary.com)
* Graph Database integration
* Personalized learning recommendations

## Author

Seokwon Kim

Built for practical English learning and long-term vocabulary retention.
