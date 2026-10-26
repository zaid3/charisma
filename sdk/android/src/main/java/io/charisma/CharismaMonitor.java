package io.charisma;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.Future;

/** Explicit Android error reporting. No messages, stack traces, device IDs or user data. */
public final class CharismaMonitor implements AutoCloseable {
    public interface Transport { void send(URL endpoint, String appId, String siteKey, byte[] body) throws IOException; }
    private final URL endpoint;
    private final String appId, siteKey;
    private final Transport transport;
    private final Set<String> seen = new LinkedHashSet<String>();
    private final ThreadPoolExecutor executor;
    private boolean closed;

    public CharismaMonitor(String endpoint, String appId, String siteKey) { this(endpoint, appId, siteKey, new HttpTransport()); }
    public CharismaMonitor(String endpoint, String appId, String siteKey, Transport transport) {
        try {
            URI uri = new URI(endpoint);
            if (!"https".equals(uri.getScheme()) || uri.getHost() == null || uri.getRawUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null || !appId.matches("[A-Za-z0-9_.-]{3,100}") || !siteKey.matches("[A-Za-z0-9_-]{8,80}")) throw new IllegalArgumentException("Invalid monitor configuration");
            this.endpoint = uri.toURL();
        } catch (Exception error) { throw new IllegalArgumentException("Use an HTTPS endpoint, fixed app identifier and public site key"); }
        if (transport == null) throw new IllegalArgumentException("Transport is required");
        this.appId = appId; this.siteKey = siteKey; this.transport = transport;
        executor = new ThreadPoolExecutor(1,1,0,TimeUnit.SECONDS,new ArrayBlockingQueue<Runnable>(30), runnable -> {
            Thread thread = new Thread(runnable, "charisma-monitor"); thread.setDaemon(true); return thread;
        },new ThreadPoolExecutor.AbortPolicy());
    }

    /** A fixed screen label, never a customer name, URL or error message. */
    public synchronized boolean record(String screen) {
        if (closed || screen == null || !screen.matches("[A-Za-z0-9_-]{1,40}") || seen.size() >= 30 || !seen.add(screen)) return false;
        final byte[] payload = ("{\"code\":\"android-error\",\"error\":\"Unknown\",\"file\":\"\",\"line\":0,\"column\":0,\"count\":1,\"page\":\"" + screen + "\"}").getBytes(StandardCharsets.UTF_8);
        try {
            executor.execute(() -> { try { transport.send(endpoint, appId, siteKey, payload); } catch (Exception ignored) { /* No recursive error reporting or retries. */ } });
            return true;
        } catch (java.util.concurrent.RejectedExecutionException ignored) { return false; }
    }

    /** Test/controlled-shutdown helper; do not wait on the UI thread. */
    public boolean awaitIdle(long timeoutMillis) throws Exception {
        Future<?> barrier = executor.submit(() -> {});
        barrier.get(timeoutMillis, TimeUnit.MILLISECONDS); return true;
    }
    @Override public synchronized void close() { closed = true; executor.shutdownNow(); }

    private static final class HttpTransport implements Transport {
        @Override public void send(URL endpoint, String appId, String siteKey, byte[] body) throws IOException {
            HttpURLConnection connection = (HttpURLConnection) endpoint.openConnection();
            try {
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(5000); connection.setReadTimeout(5000);
                connection.setRequestMethod("POST"); connection.setDoOutput(true); connection.setUseCaches(false);
                connection.setRequestProperty("Content-Type", "application/json");
                connection.setRequestProperty("X-Charisma-App-ID", appId);
                connection.setRequestProperty("X-Charisma-Site-Key", siteKey);
                connection.setRequestProperty("Cookie", "");
                connection.setFixedLengthStreamingMode(body.length);
                try (java.io.OutputStream output = connection.getOutputStream()) { output.write(body); }
                if (connection.getResponseCode() != 202) throw new IOException("Report not accepted");
            } finally { connection.disconnect(); }
        }
    }
}
