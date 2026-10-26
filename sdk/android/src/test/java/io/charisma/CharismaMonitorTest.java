package io.charisma;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
public final class CharismaMonitorTest {
    public static void main(String[] args) throws Exception {
        List<String> payloads = new ArrayList<String>();
        CharismaMonitor monitor = new CharismaMonitor("https://monitor.example/ingest/native", "io.example.app", "public-fixture-key", (url,app,key,body) -> payloads.add(new String(body,StandardCharsets.UTF_8)));
        if (!monitor.record("checkout") || monitor.record("checkout") || monitor.record("private@example.com")) throw new AssertionError("Deduplication/privacy failed");
        monitor.awaitIdle(2000);
        if (payloads.size()!=1 || !payloads.get(0).contains("android-error") || payloads.get(0).contains("message")) throw new AssertionError("Payload changed");
        monitor.close(); if (monitor.record("settings")) throw new AssertionError("Stop failed");
        try { new CharismaMonitor("http://monitor.example/ingest/native", "io.example.app", "public-fixture-key"); throw new AssertionError("HTTP accepted"); }
        catch (IllegalArgumentException expected) { }
        CharismaMonitor unavailable = new CharismaMonitor("https://monitor.example/ingest/native", "io.example.app", "public-fixture-key", (u,a,k,b) -> { throw new java.io.IOException("offline"); });
        unavailable.record("checkout"); unavailable.awaitIdle(2000); unavailable.close();
        System.out.println("Android monitor privacy, transport, deduplication and stop checks passed.");
    }
}
