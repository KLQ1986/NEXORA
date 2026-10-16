// Apple's frame processors (VideoToolbox VTFrameProcessor, macOS 15.4+ / 26+) for NEXORA's Visual Quality engine.
// Built once by scripts/setup-apple-frames.sh into data/tools/apple_frames/apple_frames; called by adapters/apple_frames.py.
//
//   apple_frames probe
//   apple_frames denoise     <in> <out> <t_in> <seconds> <strength 0..1>
//   apple_frames interpolate <in> <out> <t_in> <seconds> <fps>
//   apple_frames superres    <in> <out> <t_in> <seconds>            (×4, sources up to 1920×1080)
//
// The result is picture only, ProRes 422 HQ in a .mov, with the source's colour description; the caller puts the sound back.
// One JSON line on stdout says what was done, or {"error": ...}.
import AVFoundation
import CoreMedia
import Foundation
import VideoToolbox

func say(_ obj: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: obj)
    print(String(data: data, encoding: .utf8)!)
}

func fourcc(_ s: String) -> OSType { s.utf8.reduce(0) { ($0 << 8) | OSType($1) } }

struct Fail: Error { let message: String }

final class Source {
    let reader: AVAssetReader
    let output: AVAssetReaderTrackOutput
    let width: Int, height: Int
    let rate: Double
    let colour: [String: Any]

    init(_ url: URL, tIn: Double, seconds: Double, format: OSType) async throws {
        let asset = AVURLAsset(url: url)
        guard let track = try await asset.loadTracks(withMediaType: .video).first else { throw Fail(message: "no video track") }
        let size = try await track.load(.naturalSize)
        width = Int(size.width); height = Int(size.height)
        rate = Double(try await track.load(.nominalFrameRate))
        var c: [String: Any] = [:]
        if let fd = try await track.load(.formatDescriptions).first {
            let ext = CMFormatDescriptionGetExtensions(fd) as? [String: Any] ?? [:]
            if let p = ext[kCVImageBufferColorPrimariesKey as String] { c[AVVideoColorPrimariesKey] = p }
            if let t = ext[kCVImageBufferTransferFunctionKey as String] { c[AVVideoTransferFunctionKey] = t }
            if let m = ext[kCVImageBufferYCbCrMatrixKey as String] { c[AVVideoYCbCrMatrixKey] = m }
        }
        // AVAssetWriter takes all three colour keys or none: a source that names only some of them is written undescribed.
        colour = c.count == 3 ? c : [:]
        reader = try AVAssetReader(asset: asset)
        if seconds > 0 {
            reader.timeRange = CMTimeRange(start: CMTime(seconds: tIn, preferredTimescale: 600), duration: CMTime(seconds: seconds, preferredTimescale: 600))
        }
        output = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: format, kCVPixelBufferIOSurfacePropertiesKey as String: [:]])
        output.alwaysCopiesSampleData = false
        reader.add(output)
        guard reader.startReading() else { throw Fail(message: "cannot read: \(reader.error?.localizedDescription ?? "?")") }
    }

    func next() -> (CVPixelBuffer, CMTime)? {
        while let sb = output.copyNextSampleBuffer() {
            if let pb = CMSampleBufferGetImageBuffer(sb) { return (pb, CMSampleBufferGetPresentationTimeStamp(sb)) }
        }
        return nil
    }
}

final class Sink {
    let writer: AVAssetWriter
    let input: AVAssetWriterInput
    let adaptor: AVAssetWriterInputPixelBufferAdaptor
    var transfer: VTPixelTransferSession?
    var pool: CVPixelBufferPool?
    let width: Int, height: Int
    var start: CMTime?

    init(_ url: URL, width: Int, height: Int, colour: [String: Any]) throws {
        try? FileManager.default.removeItem(at: url)
        writer = try AVAssetWriter(outputURL: url, fileType: .mov)
        var settings: [String: Any] = [AVVideoCodecKey: AVVideoCodecType.proRes422HQ, AVVideoWidthKey: width, AVVideoHeightKey: height]
        if !colour.isEmpty { settings[AVVideoColorPropertiesKey] = colour }
        input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
        input.expectsMediaDataInRealTime = false
        adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_422YpCbCr10BiPlanarVideoRange, kCVPixelBufferWidthKey as String: width,
            kCVPixelBufferHeightKey as String: height, kCVPixelBufferIOSurfacePropertiesKey as String: [:]])
        writer.add(input)
        self.width = width; self.height = height
        guard writer.startWriting() else { throw Fail(message: "cannot write: \(writer.error?.localizedDescription ?? "?")") }
        VTPixelTransferSessionCreate(allocator: nil, pixelTransferSessionOut: &transfer)
    }

    func append(_ pb: CVPixelBuffer, at t: CMTime) throws {
        if start == nil { start = t; writer.startSession(atSourceTime: t) }
        if pool == nil { pool = adaptor.pixelBufferPool }
        var out: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, pool!, &out)
        guard let dst = out else { throw Fail(message: "no buffer to write into") }
        VTPixelTransferSessionTransferImage(transfer!, from: pb, to: dst)   // from the processor's format to one ProRes takes
        while !input.isReadyForMoreMediaData { usleep(1000) }
        if !adaptor.append(dst, withPresentationTime: t) { throw Fail(message: "append failed: \(writer.error?.localizedDescription ?? "?")") }
    }

    func finish() {
        input.markAsFinished()
        let done = DispatchSemaphore(value: 0)
        writer.finishWriting { done.signal() }
        done.wait()
    }
}

func run(_ processor: VTFrameProcessor, _ parameters: any VTFrameProcessorParameters) throws {
    let done = DispatchSemaphore(value: 0)
    var failure: Error?
    processor.process(parameters: parameters) { _, err in failure = err; done.signal() }
    done.wait()
    if let e = failure { throw e }
}

func pick(_ supported: [NSNumber], prefer: [String]) -> OSType? {
    let have = Set(supported.map { $0.uint32Value })
    return prefer.map(fourcc).first { have.contains($0) }
}

func newBuffer(_ attributes: [String: Any], width: Int, height: Int) -> CVPixelBuffer? {
    var pool: CVPixelBufferPool?
    CVPixelBufferPoolCreate(nil, nil, attributes as CFDictionary, &pool)
    var pb: CVPixelBuffer?
    if let pool { CVPixelBufferPoolCreatePixelBuffer(nil, pool, &pb) }
    return pb
}

func denoise(_ inURL: URL, _ outURL: URL, tIn: Double, seconds: Double, strength: Float) async throws -> [String: Any] {
    let probeSource = try await Source(inURL, tIn: tIn, seconds: 0.05, format: kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange)
    let w = probeSource.width, h = probeSource.height
    guard let format = pick(VTTemporalNoiseFilterConfiguration.__supportedSourcePixelFormats, prefer: ["&xv0", "&8v0", "-xv0", "-8v0"]),
          let config = VTTemporalNoiseFilterConfiguration(frameWidth: w, frameHeight: h, sourcePixelFormat: format) else { throw Fail(message: "temporal noise filter not available for \(w)x\(h)") }
    let source = try await Source(inURL, tIn: tIn, seconds: seconds, format: format)
    let sink = try Sink(outURL, width: w, height: h, colour: source.colour)
    let processor = VTFrameProcessor()
    try processor.startSession(configuration: config)
    let prevN = config.previousFrameCount ?? 1, nextN = config.nextFrameCount ?? 2
    var window: [(CVPixelBuffer, CMTime)] = []
    var frames = 0, first = true
    let t0 = Date()
    func emit(_ i: Int) throws {
        let prev = window[max(0, i - prevN)..<i].map { VTFrameProcessorFrame(buffer: $0.0, presentationTimeStamp: $0.1)! }
        let next = window[(i + 1)..<min(window.count, i + 1 + nextN)].map { VTFrameProcessorFrame(buffer: $0.0, presentationTimeStamp: $0.1)! }
        guard let dst = newBuffer(config.destinationPixelBufferAttributes, width: w, height: h) else { throw Fail(message: "no destination buffer") }
        let p = VTTemporalNoiseFilterParameters(sourceFrame: VTFrameProcessorFrame(buffer: window[i].0, presentationTimeStamp: window[i].1)!, nextFrames: next,
                                                previousFrames: prev, destinationFrame: VTFrameProcessorFrame(buffer: dst, presentationTimeStamp: window[i].1)!,
                                                filterStrength: strength, hasDiscontinuity: first)!
        try run(processor, p)
        first = false
        try sink.append(dst, at: window[i].1)
        frames += 1
    }
    // A sliding window of previous and next frames around the one being filtered.
    var cursor = 0
    while let f = source.next() {
        window.append(f)
        while cursor < window.count - nextN { try emit(cursor); cursor += 1 }
        if cursor > prevN { window.removeFirst(cursor - prevN); cursor = prevN }
    }
    while cursor < window.count { try emit(cursor); cursor += 1 }
    processor.endSession()
    sink.finish()
    return ["op": "denoise", "frames": frames, "seconds": Date().timeIntervalSince(t0), "width": w, "height": h]
}

func interpolate(_ inURL: URL, _ outURL: URL, tIn: Double, seconds: Double, fps: Double) async throws -> [String: Any] {
    let probeSource = try await Source(inURL, tIn: tIn, seconds: 0.05, format: kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange)
    let w = probeSource.width, h = probeSource.height
    guard let config = VTFrameRateConversionConfiguration(frameWidth: w, frameHeight: h, usePrecomputedFlow: false, qualityPrioritization: .quality,
                                                         revision: VTFrameRateConversionConfiguration.defaultRevision),
          let format = pick(config.__frameSupportedPixelFormats, prefer: ["RGhA", "x420", "420v", "&xv0", "&8v0"]) else { throw Fail(message: "frame rate conversion not available") }
    let source = try await Source(inURL, tIn: tIn, seconds: seconds, format: format)
    let sink = try Sink(outURL, width: w, height: h, colour: source.colour)
    let processor = VTFrameProcessor()
    try processor.startSession(configuration: config)
    let step = 1.0 / fps
    var previous: (CVPixelBuffer, CMTime)? = nil
    var nextOut: Double? = nil
    var frames = 0
    let t0 = Date()
    while let cur = source.next() {
        let tc = cur.1.seconds
        if previous == nil {
            try sink.append(cur.0, at: cur.1); frames += 1; nextOut = tc + step; previous = cur; continue
        }
        let (pb, pt) = previous!
        let tp = pt.seconds
        var phases: [Float] = [], times: [Double] = []
        while let n = nextOut, n < tc - 1e-6 {
            phases.append(Float((n - tp) / (tc - tp))); times.append(n); nextOut = n + step
        }
        if !phases.isEmpty {
            let dsts = phases.map { _ in newBuffer(config.destinationPixelBufferAttributes, width: w, height: h)! }
            let dframes = zip(dsts, times).map { VTFrameProcessorFrame(buffer: $0.0, presentationTimeStamp: CMTime(seconds: $0.1, preferredTimescale: 60000))! }
            let p = VTFrameRateConversionParameters(sourceFrame: VTFrameProcessorFrame(buffer: pb, presentationTimeStamp: pt)!,
                                                    nextFrame: VTFrameProcessorFrame(buffer: cur.0, presentationTimeStamp: cur.1)!, opticalFlow: nil,
                                                    interpolationPhase: phases, submissionMode: .sequential, destinationFrames: dframes)!
            try run(processor, p)
            for (d, t) in zip(dsts, times) { try sink.append(d, at: CMTime(seconds: t, preferredTimescale: 60000)); frames += 1 }
        }
        if let n = nextOut, abs(n - tc) < step / 2 { try sink.append(cur.0, at: CMTime(seconds: n, preferredTimescale: 60000)); frames += 1; nextOut = n + step }
        previous = cur
    }
    processor.endSession()
    sink.finish()
    return ["op": "interpolate", "frames": frames, "fps": fps, "seconds": Date().timeIntervalSince(t0)]
}

func superres(_ inURL: URL, _ outURL: URL, tIn: Double, seconds: Double) async throws -> [String: Any] {
    let probeSource = try await Source(inURL, tIn: tIn, seconds: 0.05, format: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange)
    let w = probeSource.width, h = probeSource.height
    guard w <= 1920, h <= 1080 else { throw Fail(message: "super resolution takes sources up to 1920x1080, not \(w)x\(h)") }
    guard let config = VTSuperResolutionScalerConfiguration(frameWidth: w, frameHeight: h, scaleFactor: 4, inputType: .video, usePrecomputedFlow: false,
                                                           qualityPrioritization: .normal, revision: VTSuperResolutionScalerConfiguration.defaultRevision) else {
        throw Fail(message: "super resolution not available for \(w)x\(h)") }
    if config.configurationModelStatus != .ready {
        let done = DispatchSemaphore(value: 0); var err: Error?
        config.downloadConfigurationModel { e in err = e; done.signal() }
        done.wait()
        if let e = err { throw Fail(message: "model download failed: \(e.localizedDescription)") }
    }
    guard let format = pick(config.__frameSupportedPixelFormats, prefer: ["420v", "x420", "RGhA", "&8v0"]) else { throw Fail(message: "no pixel format") }
    let source = try await Source(inURL, tIn: tIn, seconds: seconds, format: format)
    let ow = w * 4, oh = h * 4
    let sink = try Sink(outURL, width: ow, height: oh, colour: source.colour)
    let processor = VTFrameProcessor()
    try processor.startSession(configuration: config)
    var previous: VTFrameProcessorFrame? = nil, previousOut: VTFrameProcessorFrame? = nil
    var frames = 0
    let t0 = Date()
    while let cur = source.next() {
        guard let dst = newBuffer(config.destinationPixelBufferAttributes, width: ow, height: oh) else { throw Fail(message: "no destination buffer") }
        let src = VTFrameProcessorFrame(buffer: cur.0, presentationTimeStamp: cur.1)!
        let out = VTFrameProcessorFrame(buffer: dst, presentationTimeStamp: cur.1)!
        let p = VTSuperResolutionScalerParameters(sourceFrame: src, previousFrame: previous, previousOutputFrame: previousOut, opticalFlow: nil,
                                                  submissionMode: .sequential, destinationFrame: out)!
        try run(processor, p)
        try sink.append(dst, at: cur.1)
        previous = src; previousOut = out; frames += 1
    }
    processor.endSession()
    sink.finish()
    return ["op": "superres", "frames": frames, "width": ow, "height": oh, "seconds": Date().timeIntervalSince(t0)]
}

let a = CommandLine.arguments
do {
    guard a.count >= 2 else { throw Fail(message: "usage: apple_frames probe|denoise|interpolate|superres ...") }
    switch a[1] {
    case "probe":
        say(["denoise": VTTemporalNoiseFilterConfiguration.isSupported, "interpolate": VTFrameRateConversionConfiguration.isSupported,
             "superres": VTSuperResolutionScalerConfiguration.isSupported, "superres_scales": VTSuperResolutionScalerConfiguration.supportedScaleFactors])
    case "denoise":
        say(try await denoise(URL(fileURLWithPath: a[2]), URL(fileURLWithPath: a[3]), tIn: Double(a[4])!, seconds: Double(a[5])!, strength: Float(a[6])!))
    case "interpolate":
        say(try await interpolate(URL(fileURLWithPath: a[2]), URL(fileURLWithPath: a[3]), tIn: Double(a[4])!, seconds: Double(a[5])!, fps: Double(a[6])!))
    case "superres":
        say(try await superres(URL(fileURLWithPath: a[2]), URL(fileURLWithPath: a[3]), tIn: Double(a[4])!, seconds: Double(a[5])!))
    default:
        throw Fail(message: "unknown operation \(a[1])")
    }
} catch let f as Fail {
    say(["error": f.message]); exit(1)
} catch {
    say(["error": "\(error)"]); exit(1)
}
