# FDEM TX Controller PWA

This directory is a static GitHub Pages application; it has no build step and no server-side component.

## Supported field use

Use an installed Chrome or Edge PWA on desktop or Android. Web Bluetooth and Web Serial require HTTPS and are not supported consistently by Safari, Firefox, or iPhone/iPad browsers.

Open the deployed GitHub Pages site once while online, wait for the **Offline ready** notice, then install it from the browser. The cached interface can subsequently connect to the transmitter through local BLE or USB with the phone/laptop in airplane mode. A first-ever visit cannot work without a network connection.

## Deployment and update test

GitHub Pages must publish the `docs/` directory. After deploying, open the site online, install it, then enable airplane mode and relaunch/refresh it. When a new service worker is available, the UI shows **Update ready**; select it only when it is safe to reload the controller.
