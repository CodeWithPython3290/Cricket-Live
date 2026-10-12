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

1. Push this folder to a public GitHub repository, including the `templates` folder and `game_server.py`.
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, and click **Create app**.
3. Select the repository, branch `main`, and main file `streamlit_app.py`, then click **Deploy**.

## 3D Cricket League

A cartoon cricket game. Pick an IPL team, choose how many overs and wickets to play, then take on the CPU (Easy, Medium or Hard) or a friend online.

| | Batting | Bowling |
|---|---|---|
| Keys | `Space` / click to swing · hold `←` `→` to aim · hold `↑` to loft · hold `↓` to defend | `A` `D` line · `W` `S` length · `Q` fast/spin · `F` bowl |

### Online play

Online play runs on `game_server.py`, a small server in this project. It uses only Python's standard library, so there's nothing extra to install or sign up for. The server:

- stores player accounts (username and password; passwords are salted and hashed) in `game_data.db`, a local SQLite file that isn't uploaded to GitHub
- runs match rooms with 5-letter codes
- passes each ball between the two players
- serves the game page itself

**The server starts automatically** when you run the Streamlit app. Its address, such as `http://192.168.1.20:8765`, is shown on the game's template card. You can also run it on its own:

```bash
python game_server.py          # add --port 9000 to use a different port
```

**To play a friend:**

1. Run the app (or `game_server.py`) on one computer.
2. Both players open the server address in a browser. The computer running the server can also use **▶ Play in new tab** in the app.
3. Each player clicks **Play online** and creates an account (or signs in).
4. One player clicks **Create a room** and shares the 5-letter code. The other types it in and clicks **Join**. The host then clicks **Start match**.

**Good to know:**

- Both computers must be on the **same network** (same Wi-Fi). To play over the internet, the server has to be reachable from outside your network, for example through port forwarding on your router.
- On **Streamlit Community Cloud**, the server starts but other computers can't reach it, because Streamlit Cloud only exposes the app's own web page. For online matches, run the app or `game_server.py` on your own computer.
- If Windows asks whether to allow Python through the firewall, click **Allow** (private networks). Otherwise friends can't connect.

## Data sources

- Scores: `https://static.cricinfo.com/rss/livescores.xml` (free, public RSS feed)
- Streams: only official, publicly embeddable YouTube streams. Paid broadcasts are not included.
