# Hack or Treat: Dracula's Personal Catalogue

**Mirrors fail him. We don't.**

Count Dracula lives at Casa Loma in Toronto and hosts a high-society gala every week. A nobleman can never wear the same outfit twice, but there's a problem: vampires have no reflection. He can't check how a coat drapes, whether his cravat is straight, or if his fangs are spotless.

Dracula's Personal Catalogue is his replacement mirror. It's a set of web tools that captures him in 3D, learns his taste, and sends him shopping across Toronto for the next gala.

## How it works

```
 1. Capture him         2. Learn his taste       3. Dress him            4. Shop for it
 Camera to 3D      →    Outfit Studio       →    Sartorial Mirror   →    Toronto Route Matrix
 photo → 3D model       photo + up to 3          trend search, 3D        boutique checklist,
 in Blender             favourite styles         try-on, party ledger    HST totals, map route
```

## What's inside

| Page | What it does |
| --- | --- |
| [`count_dracula_the_sartorial_mirror_project - Copy.html`](count_dracula_the_sartorial_mirror_project%20-%20Copy.html) | The project overview and the main pipeline: why mirrors matter, an AI fashion-trend search tuned to the gala venue and Toronto weather, a 3D LiDAR try-on, a Toronto shopping cart in CAD, and a ledger so no outfit is ever repeated. Includes a starter Python (Flask) `app.py` with the four API routes. |
| [`dracula_outfit_studio.html`](dracula_outfit_studio.html) | The intake form. Upload one front-facing photo (or open Camera to 3D), then pick up to three styles, from Victorian Revival to Neo-Gothic Streetwear. The profile is saved in the browser. |
| [`findingshops.html`](findingshops.html) | Dracula's Toronto Shopping & Route Matrix. Tick garments to build a list across Holt Renfrew, State & Liberty and Borderline Plus, see the subtotal with 13% Ontario HST against a budget, view the stops on a live map starting from Casa Loma, and open a multi-stop route in Google Maps. Also has a print/copy manifest and a "Midnight Mode". |
| [`camera-to-blender/`](camera-to-blender/) | Camera to 3D. Take or upload a photo on your phone; the background is removed, a 3D model is generated, and it appears in Blender within a minute. See its [README](camera-to-blender/README.md). |

## Running it

### The web pages

The three HTML pages are self-contained and need no build step. Open any of them in a browser (an internet connection is needed for Tailwind, Google Fonts and the map tiles).

### Camera to 3D

You'll need Python 3.10+, Blender 3.0+ and a [Tripo3D](https://platform.tripo3d.ai/) API key. A [Gemini](https://aistudio.google.com/) API key is optional and removes photo backgrounds.

```bash
cd camera-to-blender
pip install -r requirements.txt
cp .env.example .env
```

Add your keys to `.env`, then start the server on port 8001, which is where the Outfit Studio's **Camera to 3D** button points:

```bash
uvicorn relay_server:app --host 0.0.0.0 --port 8001
```

Install `ws_import_addon.zip` in Blender, open the **WS Import** tab (press `N` in the viewport) and connect to `ws://localhost:8001/ws?client=blender`. To use a phone camera, which needs HTTPS, run `ngrok http 8001` and follow the steps in the [Camera to 3D README](camera-to-blender/README.md).

## Built with

HTML5, CSS3, JavaScript, Tailwind CSS, Google Fonts, SVG, Canvas, localStorage, Leaflet, Google Maps, Three.js, WebGL, model-viewer, Python, FastAPI, Uvicorn, WebSockets, httpx, Blender (`bpy`), Google Gemini, Tripo3D and ngrok.

## Status

This is a hackathon build. The Outfit Studio, the Shopping & Route Matrix and Camera to 3D work end to end. In the Sartorial Mirror page, the trend search, LiDAR try-on and party ledger show simulated output, and `app.py` is a skeleton for the real backend.

## Team

- Alice Nguyen ([@aliceenguyen](https://github.com/aliceenguyen))
- [@Hope-C](https://github.com/Hope-C)
