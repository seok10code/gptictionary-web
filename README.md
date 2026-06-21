# GPTictionary

GPTictionary is a personal English learning web app that helps you save vocabulary, ask English questions, take quizzes, and practice writing with AI feedback.

## Features

### Vocabulary Search
- Words, phrases, idioms, phrasal verbs
- AI-generated explanations
- Automatic storage

### Writing Lab
- AI writing challenges
- Grammar correction
- Natural rewrite
- Vocabulary scoring
- Required-word tracking

### AI Questions
- Semantic search with Qdrant
- Similar question retrieval
- Saved answers

### Quiz
- Auto-generated quiz questions
- Correct/wrong tracking
- Quiz history

### TTS
- Click words and examples
- Browser-based speech synthesis

## Tech Stack

### Backend
- FastAPI
- SQLAlchemy
- PyMySQL
- Jinja2

### Database
- MariaDB
- Qdrant

### AI
- OpenAI API
- Embeddings
- GPT-based feedback

## Pages

- /
- /words
- /search
- /quiz
- /questions
- /writing
- /stats
- /settings

## Database Tables

### words
Vocabulary and phrase storage

### quiz_questions
Generated quiz questions

### quiz_logs
Quiz history

### writing_submissions
Writing Lab submissions

## Local Run

```bash
python -m venv venv
source venv/bin/activate

pip install -r requirements.txt

python backend/app/db/create_tables.py

uvicorn backend.app.main:app --reload
```

## Roadmap

- Grammar analytics
- Vocabulary usage analytics
- Writing streaks
- Personalized AI coach
- Conversation challenges
- Better TTS

## Recent Update (v0.3)

- Writing Lab
- AI correction
- Phrase support
- TTS
- Writing storage
- Vocabulary usage tracking
