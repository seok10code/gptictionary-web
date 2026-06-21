# GPTictionary

GPTictionary is a personal English learning web app that helps you save vocabulary, ask English questions, take quizzes, and practice writing with AI feedback.

The goal is not just to memorize words, but to actually use them in writing and conversation.

---

## Features

### Vocabulary Search

Search for English words, phrases, idioms, phrasal verbs, and expressions.

Examples:

- `awash`
- `awash with`
- `come out`
- `pinch pennies`
- `This is it`

If the expression is not in the database, GPTictionary generates an explanation using AI and saves it automatically.

---

### Word Detail

Each saved word or expression can include:

- Korean definition
- English example sentence
- pronunciation
- synonyms
- antonyms
- part-of-speech definitions
- useful examples
- usage notes
- short real-life conversation
- formal writing examples
- etymology summary

---

### Text-to-Speech

Words and example sentences can be clicked to hear pronunciation.

Supported areas:

- Word list
- Search result
- Example sentences
- Synonyms and antonyms
- Writing Challenge required words

---

### Quiz

GPTictionary automatically creates quiz questions from saved words.

Quiz data tracks:

- correct count
- wrong count
- user answer
- correct answer
- quiz history

---

### AI Questions

Ask English-related questions and save useful answers.

Examples:

- `What does "pinch pennies" mean?`
- `How do I say "야 너 언제 출발할거야?" in English?`
- `What is the difference between "went" and "have gone"?`

Questions can be stored in Qdrant for semantic search and similar-question retrieval.

---

### Writing Lab

Writing Lab creates AI-powered writing challenges using words from your vocabulary database.

Example challenge:

```text
Topic:
Describe a time when you had to save money.

Required words:
- pinch pennies
- awash
- contractor

Target:
80-120 words
