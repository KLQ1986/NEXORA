// What the frameworks that come with macOS can tell about pictures and sound, as JSON on standard output.
// Built once by the `vision` and `sound` adapters (apple.py) with the system's Swift compiler; nothing leaves the machine.
//
//   apple-see look <frames.json>                 one record per picture listed (a JSON array of paths)
//   apple-see listen <audio file> <window> <hop>  what kind of sound each window holds
//
// Every box is [x, y, width, height] as shares of the picture, measured from its top left corner.
import AVFoundation
import Foundation
import SoundAnalysis
import Vision

func box(_ r: CGRect) -> [Double] {
    [Double(r.minX), Double(1 - r.maxY), Double(r.width), Double(r.height)].map { ($0 * 10000).rounded() / 10000 }
}

func round4(_ v: Double) -> Double { (v * 10000).rounded() / 10000 }

func emit(_ value: Any) {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}

func point(_ p: VNRecognizedPoint?) -> [Double]? {
    guard let p = p, p.confidence > 0.1 else { return nil }
    return [round4(Double(p.location.x)), round4(Double(1 - p.location.y)), round4(Double(p.confidence))]
}

// How open the mouth is: the height of the inner lips over their width. Close to zero when the lips are shut.
func mouthOpen(_ landmarks: VNFaceLandmarks2D?) -> Double? {
    guard let lips = landmarks?.innerLips, lips.pointCount > 2 else { return nil }
    let pts = lips.normalizedPoints
    let xs = pts.map { Double($0.x) }, ys = pts.map { Double($0.y) }
    let width = (xs.max()! - xs.min()!)
    return width > 0 ? round4((ys.max()! - ys.min()!) / width) : nil
}

func look(_ path: String) -> [String: Any] {
    var out: [String: Any] = ["path": path]
    let url = URL(fileURLWithPath: path)
    let handler = VNImageRequestHandler(url: url)
    let classify = VNClassifyImageRequest()
    let faces = VNDetectFaceLandmarksRequest()
    let quality = VNDetectFaceCaptureQualityRequest()
    let humans = VNDetectHumanRectanglesRequest()
    humans.upperBodyOnly = false
    let poses = VNDetectHumanBodyPoseRequest()
    let hands = VNDetectHumanHandPoseRequest()
    hands.maximumHandCount = 4
    let animals = VNRecognizeAnimalsRequest()
    let text = VNRecognizeTextRequest()
    text.recognitionLevel = .accurate
    text.recognitionLanguages = ["vi-VT", "en-US"]
    text.usesLanguageCorrection = true
    let horizon = VNDetectHorizonRequest()
    let salient = VNGenerateAttentionBasedSaliencyImageRequest()
    let aesthetics = VNCalculateImageAestheticsScoresRequest()
    let print = VNGenerateImageFeaturePrintRequest()
    do {
        try handler.perform([classify, faces, humans, poses, hands, animals, text, horizon, salient, aesthetics, print])
        try? handler.perform([quality])
    } catch {
        out["error"] = "\(error)"
        return out
    }
    out["classes"] = (classify.results ?? []).filter { $0.confidence >= 0.1 }.prefix(20).map { [$0.identifier, round4(Double($0.confidence))] as [Any] }
    let qualities = (quality.results ?? []).map { (box($0.boundingBox), $0.faceCaptureQuality.map { Double($0) }) }
    out["faces"] = (faces.results ?? []).map { f -> [String: Any] in
        var face: [String: Any] = ["box": box(f.boundingBox), "confidence": round4(Double(f.confidence))]
        if let yaw = f.yaw { face["yaw"] = round4(Double(truncating: yaw)) }
        if let roll = f.roll { face["roll"] = round4(Double(truncating: roll)) }
        if let mouth = mouthOpen(f.landmarks) { face["mouth"] = mouth }
        let b = box(f.boundingBox)
        if let q = qualities.first(where: { abs($0.0[0] - b[0]) < 0.02 && abs($0.0[1] - b[1]) < 0.02 })?.1 { face["quality"] = round4(q) }
        // A print of the face and a little around it, to know the same person again in another shot. Only for faces big enough to tell apart.
        if f.boundingBox.height > 0.08 {
            let around = f.boundingBox.insetBy(dx: -f.boundingBox.width * 0.25, dy: -f.boundingBox.height * 0.25).intersection(CGRect(x: 0, y: 0, width: 1, height: 1))
            let facePrint = VNGenerateImageFeaturePrintRequest()
            facePrint.regionOfInterest = around
            if (try? handler.perform([facePrint])) != nil, let fp = facePrint.results?.first, fp.elementType == .float {
                var values = [Float](repeating: 0, count: fp.elementCount)
                fp.data.withUnsafeBytes { raw in for i in 0..<fp.elementCount { values[i] = raw.load(fromByteOffset: i * 4, as: Float.self) } }
                face["print"] = values.map { round4(Double($0)) }
            }
        }
        return face
    }
    out["humans"] = (humans.results ?? []).map { ["box": box($0.boundingBox), "confidence": round4(Double($0.confidence))] }
    let names: [(String, VNHumanBodyPoseObservation.JointName)] = [("nose", .nose), ("neck", .neck), ("root", .root),
        ("left_shoulder", .leftShoulder), ("right_shoulder", .rightShoulder), ("left_wrist", .leftWrist), ("right_wrist", .rightWrist),
        ("left_hip", .leftHip), ("right_hip", .rightHip), ("left_knee", .leftKnee), ("right_knee", .rightKnee),
        ("left_ankle", .leftAnkle), ("right_ankle", .rightAnkle)]
    out["poses"] = (poses.results ?? []).map { pose -> [String: Any] in
        var joints: [String: Any] = [:]
        for (name, joint) in names { if let p = point(try? pose.recognizedPoint(joint)) { joints[name] = p } }
        return joints
    }
    out["hands"] = (hands.results ?? []).compactMap { h -> [String: Any]? in
        guard h.confidence > 0.3, let pts = try? h.recognizedPoints(.all) else { return nil }
        let seen = pts.values.filter { $0.confidence > 0.3 }
        guard seen.count >= 6 else { return nil }
        let xs = seen.map { Double($0.location.x) }, ys = seen.map { Double(1 - $0.location.y) }
        return ["box": [xs.min()!, ys.min()!, xs.max()! - xs.min()!, ys.max()! - ys.min()!].map(round4), "confidence": round4(Double(h.confidence)),
                "chirality": h.chirality == .left ? "left" : h.chirality == .right ? "right" : "unknown"]
    }
    out["animals"] = (animals.results ?? []).map { a -> [String: Any] in
        ["box": box(a.boundingBox), "label": a.labels.first?.identifier ?? "", "confidence": round4(Double(a.labels.first?.confidence ?? 0))]
    }
    out["text"] = (text.results ?? []).compactMap { t -> [String: Any]? in
        guard let c = t.topCandidates(1).first else { return nil }
        return ["text": c.string, "confidence": round4(Double(c.confidence)), "box": box(t.boundingBox)]
    }
    if let h = horizon.results?.first { out["horizon"] = round4(Double(h.angle) * 180 / Double.pi) }
    if let s = salient.results?.first { out["salient"] = (s.salientObjects ?? []).map { box($0.boundingBox) } }
    if let a = aesthetics.results?.first { out["aesthetic"] = round4(Double(a.overallScore)); out["utility"] = a.isUtility }
    if let p = print.results?.first {
        var values = [Float](repeating: 0, count: p.elementCount)
        if p.elementType == .float {
            p.data.withUnsafeBytes { raw in for i in 0..<p.elementCount { values[i] = raw.load(fromByteOffset: i * 4, as: Float.self) } }
            out["print"] = values.map { round4(Double($0)) }
        }
    }
    return out
}

final class Windows: NSObject, SNResultsObserving {
    var rows: [[String: Any]] = []
    func request(_ request: SNRequest, didProduce result: SNResult) {
        guard let c = result as? SNClassificationResult else { return }
        let top = c.classifications.prefix(5).filter { $0.confidence >= 0.05 }.map { [$0.identifier, round4(Double($0.confidence))] as [Any] }
        rows.append(["t": round4(c.timeRange.start.seconds), "d": round4(c.timeRange.duration.seconds), "top": top])
    }
}

let args = CommandLine.arguments
guard args.count >= 3 else {
    FileHandle.standardError.write("usage: apple-see look <frames.json> | listen <audio> <window> <hop>\n".data(using: .utf8)!)
    exit(2)
}
switch args[1] {
case "look":
    let list = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: args[2]))) as! [String]
    for path in list { autoreleasepool { emit(look(path)) } }
case "read":
    // Text only, for a second look at frames drawn larger where small text was likely (a phone, a screen, a page).
    let list = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: args[2]))) as! [String]
    for path in list {
        autoreleasepool {
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.recognitionLanguages = ["vi-VT", "en-US"]
            request.usesLanguageCorrection = true
            request.minimumTextHeight = 0.008
            let handler = VNImageRequestHandler(url: URL(fileURLWithPath: path))
            try? handler.perform([request])
            let text = (request.results ?? []).compactMap { t -> [String: Any]? in
                guard let c = t.topCandidates(1).first else { return nil }
                return ["text": c.string, "confidence": round4(Double(c.confidence)), "box": box(t.boundingBox)]
            }
            emit(["path": path, "text": text])
        }
    }
case "listen":
    let window = args.count > 3 ? Double(args[3]) ?? 1.0 : 1.0
    let hop = args.count > 4 ? Double(args[4]) ?? 0.5 : 0.5
    let analyzer = try SNAudioFileAnalyzer(url: URL(fileURLWithPath: args[2]))
    let request = try SNClassifySoundRequest(classifierIdentifier: .version1)
    request.windowDuration = CMTime(seconds: window, preferredTimescale: 1000)
    request.overlapFactor = max(0, min(0.9, 1 - hop / window))
    let observer = Windows()
    try analyzer.add(request, withObserver: observer)
    analyzer.analyze()
    emit(["windows": observer.rows])
case "version":
    emit(["version": 1])
default:
    exit(2)
}
