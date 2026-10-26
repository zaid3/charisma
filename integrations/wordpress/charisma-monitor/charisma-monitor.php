<?php
/**
 * Plugin Name: Charisma Monitor
 * Description: Adds bounded browser error and usability reporting to an authorised WordPress site.
 * Version: 0.2.0-rc.1
 * Requires at least: 6.3
 * Requires PHP: 7.4
 * Author: Ahtashamul Haque
 * License: Apache-2.0
 */

if (!defined('ABSPATH')) {
    exit;
}

function charisma_wp_configuration() {
    if (!defined('CHARISMA_MONITOR_ORIGIN') || !defined('CHARISMA_SITE_KEY')) {
        return null;
    }
    $origin = CHARISMA_MONITOR_ORIGIN;
    $key = CHARISMA_SITE_KEY;
    $label = defined('CHARISMA_PAGE_LABEL') ? CHARISMA_PAGE_LABEL : 'wordpress';
    if (!is_string($origin) || !is_string($key) || !is_string($label)
        || !preg_match('/\A[A-Za-z0-9_-]{8,80}\z/', $key)
        || !preg_match('/\A[A-Za-z0-9_-]{1,40}\z/', $label)
        || !preg_match('#\Ahttps://[A-Za-z0-9.-]+(?::[0-9]{1,5})?/?\z#', $origin)) {
        return null;
    }
    $parts = wp_parse_url($origin);
    if (!$parts || empty($parts['host']) || (isset($parts['port']) && ($parts['port'] < 1 || $parts['port'] > 65535))) {
        return null;
    }
    return array('origin' => rtrim($origin, '/'), 'key' => $key, 'page' => $label);
}

function charisma_wp_enqueue() {
    if (is_admin() || !class_exists('WP_HTML_Tag_Processor')) {
        return;
    }
    $config = charisma_wp_configuration();
    // Integrate this filter with the site's existing consent/access policy.
    if (!$config || !apply_filters('charisma_monitor_enabled', true)) {
        return;
    }
    wp_enqueue_script('charisma-monitor', $config['origin'] . '/monitor.js', array(), null,
        array('strategy' => 'defer', 'in_footer' => true));
}

function charisma_wp_script_attributes($tag, $handle) {
    if ($handle !== 'charisma-monitor' || !class_exists('WP_HTML_Tag_Processor')) {
        return $tag;
    }
    $config = charisma_wp_configuration();
    if (!$config) {
        return $tag;
    }
    $processor = new WP_HTML_Tag_Processor($tag);
    if ($processor->next_tag('SCRIPT')) {
        $processor->set_attribute('data-endpoint', $config['origin'] . '/ingest');
        $processor->set_attribute('data-site-key', $config['key']);
        $processor->set_attribute('data-page', $config['page']);
    }
    return $processor->get_updated_html();
}

add_action('wp_enqueue_scripts', 'charisma_wp_enqueue');
add_filter('script_loader_tag', 'charisma_wp_script_attributes', 10, 2);
