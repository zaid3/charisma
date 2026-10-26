// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "CharismaMonitor",
    platforms: [.iOS(.v15), .macOS(.v12)],
    products: [.library(name: "CharismaMonitor", targets: ["CharismaMonitor"])],
    targets: [.target(name: "CharismaMonitor"), .testTarget(name: "CharismaMonitorTests", dependencies: ["CharismaMonitor"])]
)
