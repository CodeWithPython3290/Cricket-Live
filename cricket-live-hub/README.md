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

1. Push this folder to a public GitHub repository, including the `templates` folder.
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, and click **Create app**.
3. Select the repository, branch `main`, and main file `streamlit_app.py`, then click **Deploy**.

## 3D Cricket League

Pick an IPL team and play:

- **vs CPU**: Easy, Medium or Hard.
- **2 Players**: two people take turns on one keyboard.
- **Online**: players create accounts and play each other from different computers.

The match setup screen lets you choose the number of overs and wickets.

| | Batting | Bowling |
|---|---|---|
| Keys | `Space` / click to swing · hold `←` `→` to aim · hold `↑` to loft · hold `↓` to defend | `A` `D` line · `W` `S` length · `Q` fast/spin · `F` bowl |

### Online play setup (one time, about 5 minutes)

Online play uses a free [Supabase](https://supabase.com) project for accounts and live match rooms.

1. **Create a project.** Sign in at supabase.com, then click **New project**. Any name and region will do.
2. **Create the accounts table.** Open **SQL Editor → New query**, paste in all of [`supabase_setup.sql`](supabase_setup.sql), and click **Run**.
3. **Email confirmation (optional).** Go to **Authentication → Sign In / Providers → Email**. If you turn off **Confirm email**, players can play as soon as they sign up. If you leave it on, they must click a link in their inbox first.
4. **Copy your keys.** Go to **Project Settings → API** (or **Data API**) and copy the **Project URL** and the **anon public** key.
5. **Give the keys to the app:**
   - **Streamlit Community Cloud:** open your app → **⋮ → Settings → Secrets**, paste the lines below, and save.
   - **Running locally:** copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill it in. This file is git-ignored, so it won't be uploaded to GitHub.

   ```toml
   [supabase]
   url = "https://YOUR-PROJECT-ID.supabase.co"
   anon_key = "YOUR-ANON-PUBLIC-KEY"
   ```

6. Restart the app. The game's template card now shows **🌐 Online ready**.

**How a match works:** each player clicks **Play online** and signs in. One player clicks **Create a room** and shares the 5-letter code. The other enters the code and clicks **Join**. The host then clicks **Start match**.

Each player's wins and losses are saved to their account.

> The anon key is designed to be public. It appears in the game page's code, and Supabase's row-level security (set up by the SQL script) stops players from editing anyone's account but their own. Never put the **service_role** key in the app.

## Data sources

- Scores: `https://static.cricinfo.com/rss/livescores.xml` (free, public RSS feed)
- Streams: only official, publicly embeddable YouTube streams. Paid broadcasts are not included.
