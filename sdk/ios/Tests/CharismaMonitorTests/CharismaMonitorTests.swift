import XCTest
@testable import CharismaMonitor

actor Requests {
    var bodies: [Data] = []
    func add(_ data: Data) { bodies.append(data) }
    func all() -> [Data] { bodies }
}
final class CharismaMonitorTests: XCTestCase {
    func testPrivacyDeduplicationAndStop() async throws {
        let requests = Requests()
        let monitor = try CharismaMonitor(endpoint: URL(string: "https://monitor.example/ingest/native")!, appID: "io.example.app", siteKey: "public-fixture-key") { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "X-Charisma-App-ID"), "io.example.app")
            XCTAssertFalse(request.httpShouldHandleCookies)
            await requests.add(request.httpBody!)
        }
        let first = await monitor.record(screen: "checkout")
        let duplicate = await monitor.record(screen: "checkout")
        let privateLabel = await monitor.record(screen: "name@example.com")
        XCTAssertTrue(first); XCTAssertFalse(duplicate); XCTAssertFalse(privateLabel)
        await monitor.stop()
        let stopped = await monitor.record(screen: "settings")
        XCTAssertFalse(stopped)
        let bodies = await requests.all()
        XCTAssertEqual(bodies.count, 1)
        let payload = try JSONSerialization.jsonObject(with: bodies[0]) as! [String: Any]
        XCTAssertEqual(Set(payload.keys), Set(["code", "error", "file", "line", "column", "count", "page"]))
        XCTAssertEqual(payload["code"] as? String, "ios-error")
    }
    func testRejectsInsecureOrCredentialBearingEndpoints() {
        for url in ["http://monitor.example/ingest/native", "https://user:secret@monitor.example/ingest/native", "https://monitor.example/ingest/native?token=x"] {
            XCTAssertThrowsError(try CharismaMonitor(endpoint: URL(string: url)!, appID: "io.example.app", siteKey: "public-fixture-key"))
        }
    }
    func testTransportFailureIsContained() async throws {
        let monitor = try CharismaMonitor(endpoint: URL(string: "https://monitor.example/ingest/native")!, appID: "io.example.app", siteKey: "public-fixture-key") { _ in throw URLError(.timedOut) }
        let sent = await monitor.record(screen: "checkout")
        XCTAssertFalse(sent)
    }
}
