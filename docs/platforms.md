# Websites, web apps, SaaS and hosted platforms

Charisma is intended for ordinary websites, web applications, SaaS products, storefronts and native apps. Its browser monitor is framework-independent. Available features depend on the access the platform gives you; adding a browser script does not grant access to a provider's private backend.

## Compatibility and scope

| Platform | Browser monitoring | Reviewed source repairs | Gateway/database controls |
| --- | --- | --- | --- |
| Static HTML/JavaScript sites | Script in the shared page template | Supported findings in an authorised local checkout | Gateway and static release controls when you manage hosting |
| Node.js, Express and custom backends | Script in rendered HTML or the frontend bundle entry template | Supported JavaScript/frontend source findings in your checkout | Route your own services through the gateway; instrument trusted backend signals |
| React, Next.js, Vue, Angular and other web apps | Load once in the application's permitted browser script location; rescan after navigation | Supported source types and findings, with your actual build/tests | Available for infrastructure you control |
| SaaS products | Monitor the frontend you operate | Authorised application source and explicitly configured tests | Separate service policies and optional PostgreSQL tenant-scope integration |
| WordPress/WooCommerce | Included WordPress loader plugin for public frontend pages | Supported HTML/JavaScript source only; no automatic PHP/core/plugin repair | Available where you control the reverse proxy/database |
| Shopify | Storefront theme snippet where theme access and platform policy permit | Supported exported theme JavaScript/HTML assets; no Liquid-specific repair engine | No control of Shopify's private hosting, checkout or internal database |
| Wix | Custom Code snippet on eligible published sites | Supported source you actually own/export; no access to Wix's private generated backend | Only your separately controlled external services |
| Other site builders/CMSs | Possible where they permit the script and outbound reporting | Only supported source you can lawfully provide | Only infrastructure you control |

This is an integration map, not certification of every theme, plugin, site builder or framework version. Test in staging. Iframes, closed shadow roots, consent blocking, restrictive content security policies and platform sandboxes can limit what the monitor sees. No script can guarantee full coverage of every website.

The monitor serves a single installation/event list. For SaaS customer isolation, deploy separate monitor instances where required or build a reviewed tenant-authentication layer. An origin allowlist is not a tenant access-control system. Do not put customer/tenant IDs, account details or user names in page labels.

## Shared installation steps

1. Deploy the monitor over HTTPS and configure your site's exact production origin.
2. Add the public script using the platform's supported integration method, replacing the monitor address and public installation key.
3. Permit that exact monitor origin in your site's applicable `script-src` and `connect-src` CSP rules. Do not disable your CSP wholesale.
4. Connect loading/reporting to your site's existing consent policy where required.
5. Trigger a controlled test error and inspect the dashboard and request payload. Verify navigation behaviour and duplicate suppression.

Use a fixed page label. Never embed reader, operator, gateway, model or GitHub credentials in any snippet. For browser navigation that replaces content without a reload, call `window.Charisma?.scan()` after the view renders. Install once per page; avoid duplicate loaders from both a theme and a tag manager.

## WordPress and WooCommerce

The source plugin is at `integrations/wordpress/charisma-monitor`. Copy that folder into your site's `wp-content/plugins` and activate **Charisma Monitor** through WordPress. It requires WordPress 6.3+ and PHP 7.4+. Hosting plans that prohibit custom plugins cannot use this installation route.

Set these public values in your private `wp-config.php` before WordPress is loaded:

```php
define('CHARISMA_MONITOR_ORIGIN', 'https://monitor.example.com');
define('CHARISMA_SITE_KEY', 'your-public-installation-key');
define('CHARISMA_PAGE_LABEL', 'wordpress');
```

The plugin validates configuration and adds only the browser loader on public frontend pages. It preserves existing script-tag attributes through WordPress's HTML processor. It does not add database tables, change checkout logic, send customer/order data, edit themes or intercept PHP errors. No telemetry is added to the WordPress admin dashboard.

Integrate the `charisma_monitor_enabled` filter with your own consent/access policy, or control loading through your existing consent manager. WooCommerce pages are browser pages; this does not provide payment-provider internals or guaranteed coverage of third-party checkout frames. Purge relevant page caches after configuration changes. Disable the plugin to remove its loader; `window.Charisma?.stop()` stops an already-loaded monitor for the current page.

The plugin uses documented WordPress APIs and receives syntax validation in CI. Your installed theme, optimisation plugins, CSP and consent system still need an actual site integration test.

## Shopify

Copy `integrations/shopify/charisma-monitor.liquid` into an authorised development/duplicate theme, replace its public configuration and render it once from the shared storefront layout, subject to your consent policy. Preview and verify before publishing through Shopify's own theme process.

This snippet is for the **storefront theme**. Do not paste the browser monitor into Shopify's Customer Events/Web Pixels sandbox and assume it can inspect the top-level DOM. Checkout/customer-account extensions and pixels use Shopify's approved APIs and restrictions; no dedicated Shopify pixel or checkout extension is included here. Charisma does not access Shopify customer records or secretly modify its platform code.

## Wix

On a published site with a connected domain and access to Custom Code, use **Settings → Custom Code → Add Custom Code**. Replace the values in `integrations/wix/charisma-monitor.html`, choose the intended pages and an appropriate loading location. Configure the correct code category/consent behaviour for your installation. Test the published site; editor previews and HTML embed iframes are not equivalent to top-level custom code.

Avoid installing the script repeatedly on the same document. Choose loading behaviour that fits your navigation and verify subsequent page views. The monitor cannot modify Wix's hosted backend, platform authentication or internal databases. No Wix Marketplace app is included.

## Node.js, web apps and SaaS

For an Express/EJS/Pug/HTML site, place the shared script in the rendered layout. For React/Next/Vue/Angular, use the framework's supported browser script loading mechanism and invoke `scan()` after a client-side route has rendered. Charisma is a browser script, so do not execute it in a Node.js server process or during server-side rendering.

Node.js backend repairs require an authorised local checkout and your explicit test/build commands. The gateway can sit in front of an owned Node.js service independently of the frontend framework. Backend authentication outcomes can use the fixed `/edge/signal` API; only server code with the separate gateway credential may send them. See [API integration](api.md).

A SaaS product can register separate service identifiers for its owned components. Database tenant isolation requires the explicit restrictive PostgreSQL policies in [database isolation](database-isolation.md). It is not enabled merely by adding the frontend script.

## Primary platform references

* [WordPress script enqueue API](https://developer.wordpress.org/reference/functions/wp_enqueue_script/)
* [WordPress HTML tag processor](https://developer.wordpress.org/reference/classes/wp_html_tag_processor/)
* [Shopify theme code access](https://help.shopify.com/en/manual/online-store/themes/customizing-themes/edit-code)
* [Shopify Web Pixels API and sandbox model](https://shopify.dev/docs/api/web-pixels-api)
* [Wix Custom Code installation](https://support.wix.com/en/article/embedding-custom-code-on-your-site)
