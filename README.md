# TaskFlow

A premium, full-fledged task management system featuring secure session-based authentication, custom categories, instant status toggling, full-text search, multi-criteria sorting, and a hand-crafted Neo-Minimalist UI matching the MediaBuddy look.

## Features

- **User Authentication**: Secure registration and login with passwords hashed using Werkzeug.
- **Interactive Dashboard**:
  - Stats bar tracking totals, pending, in-progress, completed, and overdue tasks.
  - Multi-criteria sorting (Created Date, Due Date, Priority).
  - Quick-status pills (All, Pending, In Progress, Completed).
  - Live full-text search across titles and descriptions.
- **Task Management**:
  - CRUD operations with priority check constraints.
  - Category tag linking.
  - Interactive status toggles on cards (cycles Pending ⏳ → In Progress 🔄 → Completed ✅) via inline SVGs and AJAX fetches.
- **Category Manager**: User-scoped categories with an inline color palette picker styled as a custom color dot swatch.
- **Profile Summary**: User stats page with total tasks, completed tasks, category count, and live completion rates.

## Tech Stack

- **Backend**: Python, Flask, SQLite3
- **Frontend**: Jinja2 Templates, Vanilla CSS (dot-grid backgrounds, 2px borders, solid offset shadows)

---

## Setup & Running Locally

### Prerequisites
- Python 3.10 or higher installed.

### Steps

1. **Clone the repository:**
```bash
   git clone https://github.com/gouri-saxena06/TaskFlow.git
   cd TaskFlow
```

2. **Set up a virtual environment:**
```bash
   python3 -m venv venv
   source venv/bin/activate
```

3. **Install dependencies:**
```bash
   pip install -r requirements.txt
```

4. **Run the Flask application:**
```bash
   python app.py
```
   *Note: On the first launch, the application automatically initializes the SQLite database (`tasks.db`) using `schema.sql`.*

5. **Access the application:**
   Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your web browser.
