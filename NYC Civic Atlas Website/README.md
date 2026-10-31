# Mamdani Metre — NYC Civic Atlas UI

A locally hosted, dependency-free interface prototype for the NYC Civic Priorities & Evidence Platform.

## Open the site

For the most reliable view, run:

```powershell
node server.js
```

Then open <http://127.0.0.1:4173>. You can also double-click `index.html`; the controls run without a server. Satellite imagery, map library, and fonts require an internet connection.

## Map setup

The preview uses Leaflet for a familiar, dependable slippy map and Esri World Imagery for the satellite tiles. The Esri attribution is kept visible on the map. The map layer and scores remain illustrative placeholders until the reviewed NYC geography and indicator files are provided.

For a production build with many large data-driven polygon layers, MapLibre GL JS is a strong open-source renderer. MapTiler Satellite Hybrid can supply imagery and place labels, but requires a provider account/key and plan. Current MapTiler pricing and usage limits should be reviewed before deployment.

## Prototype behavior and limitations

- Pan and zoom the NYC satellite view; click a sample district to open its details.
- Choose a civic priority and measure, search districts, toggle labels, or switch to a district list.
- Open **User report** to attach an image, write a description, and receive a simulated topic suggestion with a clearly marked placeholder reference.
- Location is requested only when you press **Add location**.
- District shapes, scores, names, and report replies are illustrative. They are not official NYC boundaries, measurements, policy matches, or submitted reports.
- Report photos stay in the local browser preview and are not uploaded.

Low sample scores use red to flag more concern; yellow marks the middle of the scale; blue marks better conditions. The legend states this directly.
