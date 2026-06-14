import Foundation

struct APIConfig {
    /// Gemini API key — loaded from Info.plist key GEMINI_API_KEY, which is
    /// injected at build time from the local .xcconfig file (never committed).
    /// See hardware/docs/runbook.md §3 for setup instructions.
    static let geminiAPIKey: String = {
        guard let key = Bundle.main.object(forInfoDictionaryKey: "GEMINI_API_KEY") as? String,
              !key.isEmpty, key != "$(GEMINI_API_KEY)" else {
            assertionFailure("GEMINI_API_KEY not set — create Secrets.xcconfig and add it to the scheme")
            return ""
        }
        return key
    }()
}
