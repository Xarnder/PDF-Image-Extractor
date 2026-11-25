// Offline content evidence. No recognition of identity and no network requests.
import Foundation
import Vision
import ImageIO

func box(_ b: CGRect) -> [Double] {
    [Double(b.minX), Double(1 - b.maxY), Double(b.maxX), Double(1 - b.minY)]
}

let input = FileHandle.standardInput.readDataToEndOfFile()
do {
    guard let request = try JSONSerialization.jsonObject(with: input) as? [[String: Any]], request.count <= 100 else {
        throw NSError(domain: "Invalid image batch", code: 1)
    }
    var output: [[String: Any]] = []
    for item in request {
        let result: [String: Any] = autoreleasepool {
            do {
                guard let encoded = item["image"] as? String, let data = Data(base64Encoded: encoded),
                      let source = CGImageSourceCreateWithData(data as CFData, nil),
                      let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
                      image.width * image.height <= 2_000_000 else {
                    throw NSError(domain: "Invalid image", code: 2)
                }
                let faces = VNDetectFaceRectanglesRequest()
                let classes = VNClassifyImageRequest()
                let text = VNRecognizeTextRequest()
                text.recognitionLevel = .accurate
                text.usesLanguageCorrection = false
                text.minimumTextHeight = 0.006
                try VNImageRequestHandler(cgImage: image, options: [:]).perform([faces, classes, text])
                return ["faces": (faces.results ?? []).filter { $0.confidence > 0.5 }.map { box($0.boundingBox) },
                        "labels": Array((classes.results ?? []).prefix(30)).map { ["label": $0.identifier, "score": $0.confidence] as [String: Any] },
                        "texts": (text.results ?? []).compactMap { r -> [String: Any]? in
                            guard let t = r.topCandidates(1).first, t.confidence >= 0.3, t.string.count >= 2 else { return nil }
                            return ["box": box(r.boundingBox), "characters": t.string.count, "score": t.confidence]
                        }]
            } catch { return ["error": String(describing: error)] }
        }
        output.append(result)
    }
    let data = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
} catch {
    FileHandle.standardError.write(Data(String(describing: error).utf8))
    exit(1)
}
