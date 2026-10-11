# 🏏 Cricket Live Hub

A Streamlit app with two tabs:

- **Live Centre**: live cricket scores from ESPNcricinfo's public live-scores feed, refreshed every 30 seconds. International and IPL matches are listed before domestic and club games. There's also a player for official, publicly available YouTube live streams.
- **HTML Viewer**: upload or paste an HTML file to preview it, view its source, download it, or open it in a new `about:blank` browser tab.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy

1. Push this folder to a public GitHub repository.
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, and click **Create app**.
3. Select the repository, branch `main`, and main file `streamlit_app.py`, then click **Deploy**.

## Data sources

- Scores: `https://static.cricinfo.com/rss/livescores.xml` (free, public RSS feed)
- Streams: only official, publicly embeddable YouTube streams. Paid broadcasts are not included.
