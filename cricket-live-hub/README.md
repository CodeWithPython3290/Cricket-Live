# 🏏 Cricket Live Hub

A Streamlit app with two tabs:

- **Live Centre**: live cricket scores from ESPNcricinfo's public live-scores feed, refreshed every 30 seconds. International and IPL matches are listed before domestic and club games. There's also a player for official, publicly available YouTube live streams.
- **HTML Viewer**: upload or paste an HTML file to preview it, view its source, download it, or open it in a new `about:blank` browser tab. It includes a **3D Cricket League** game template.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy

1. Push this folder to a public GitHub repository, including the `templates` folder and `multiplayer.py`.
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, and click **Create app**.
3. Select the repository, branch `main`, and main file `streamlit_app.py`, then click **Deploy**.

## 3D Cricket League

A cartoon cricket game. Pick an IPL team, choose how many overs and wickets to play, then take on the CPU (Easy, Medium or Hard) or a friend online.

| | Batting | Bowling |
|---|---|---|
| Keys | `Space` / click to swing · hold `←` `→` to aim · hold `↑` to loft · hold `↓` to defend | `A` `D` line · `W` `S` length · `Q` fast/spin · `F` bowl |

### Online play

Online multiplayer is built into the app. Everything is stored in **`cricket_multiplayer.db`**, a SQLite file the app creates next to `streamlit_app.py`:

| Table | What it holds |
|---|---|
| `users`, `sessions` | Player accounts (username, plus a salted and hashed password) and sign-in tokens |
| `rooms`, `room_players` | Match rooms with 5-letter codes, and who's in each one |
| `events` | The messages the two games send each other: every delivery and result |

How it fits together:

- **The game:** `templates/cricket_league_3d.html`.
- **The bridge:** the game's **▶ Play in new tab** button is a small Streamlit component (`templates/index.html`). It opens the game, and the game sends its online requests through it.
- **The server side:** `streamlit_app.py` passes each request to `multiplayer.py`, which reads and writes the database.

Because it all runs inside the Streamlit app, **anyone who can open the deployed app, anywhere, can play**.

**To play a friend:**

1. Both players open the app (for example, your Streamlit Cloud link) and click **▶ Play in new tab** on the game card.
2. Each player clicks **Play online** and creates an account (or signs in).
3. One player clicks **Create a room** and shares the 5-letter code. The other types it in and clicks **Join**. The host then clicks **Start match**.

**Good to know:**

- **Keep the app's tab open** while you play online, because the game talks to the database through it.
- **Accounts can be wiped on Streamlit Community Cloud.** Its disk isn't permanent, so the database is wiped whenever the app restarts or is redeployed, and players then need to create accounts again. Run the app on your own computer or server to keep accounts permanently.
- **`cricket_multiplayer.db` isn't uploaded to GitHub.** It's listed in `.gitignore`.

## Data sources

- Scores: `https://static.cricinfo.com/rss/livescores.xml` (free, public RSS feed)
- Streams: only official, publicly embeddable YouTube streams. Paid broadcasts are not included.
