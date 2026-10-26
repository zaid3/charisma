import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

private final class NoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

/// Reports explicit application error categories without error messages or user data.
public actor CharismaMonitor {
    public enum Category: String, Sendable { case error = "Error", unknown = "Unknown" }
    public enum ConfigurationError: Error { case invalidConfiguration }
    public typealias Transport = @Sendable (URLRequest) async throws -> Void
    private let endpoint: URL
    private let appID: String
    private let siteKey: String
    private let transport: Transport
    private var seen = Set<String>()
    private var stopped = false

    public init(endpoint: URL, appID: String, siteKey: String, transport: Transport? = nil) throws {
        guard endpoint.scheme == "https", endpoint.host != nil,
              endpoint.user == nil, endpoint.password == nil, endpoint.query == nil, endpoint.fragment == nil,
              appID.range(of: "^[A-Za-z0-9_.-]{3,100}$", options: .regularExpression) != nil,
              siteKey.range(of: "^[A-Za-z0-9_-]{8,80}$", options: .regularExpression) != nil else {
            throw ConfigurationError.invalidConfiguration
        }
        self.endpoint = endpoint; self.appID = appID; self.siteKey = siteKey
        self.transport = transport ?? { request in
            let configuration = URLSessionConfiguration.ephemeral
            configuration.httpCookieStorage = nil
            configuration.httpShouldSetCookies = false
            configuration.urlCache = nil
            let session = URLSession(configuration: configuration, delegate: NoRedirect(), delegateQueue: nil)
            defer { session.invalidateAndCancel() }
            let (_, response) = try await session.data(for: request)
            guard let response = response as? HTTPURLResponse, response.statusCode == 202 else {
                throw URLError(.badServerResponse)
            }
        }
    }

    /// Await from a task. At most 30 distinct reports per monitor session; no retry loop.
    @discardableResult
    public func record(screen: String, category: Category = .unknown) async -> Bool {
        guard !stopped, screen.range(of: "^[A-Za-z0-9_-]{1,40}$", options: .regularExpression) != nil else { return false }
        let identity = screen + ":" + category.rawValue
        guard seen.count < 30, seen.insert(identity).inserted else { return false }
        let payload: [String: Any] = ["code": "ios-error", "error": category.rawValue,
            "file": "", "line": 0, "column": 0, "count": 1, "page": screen]
        do {
            var request = URLRequest(url: endpoint, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 8)
            request.httpMethod = "POST"
            request.httpShouldHandleCookies = false
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue(appID, forHTTPHeaderField: "X-Charisma-App-ID")
            request.setValue(siteKey, forHTTPHeaderField: "X-Charisma-Site-Key")
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
            try await transport(request)
            return true
        } catch {
            return false // Monitoring must not replace the application's error handling.
        }
    }

    public func stop() { stopped = true }
}
