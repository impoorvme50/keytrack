import AppKit
import Carbon
import IOKit.hidsystem
import SwiftUI

@MainActor final class DesktopPet: ObservableObject {
    static let shared = DesktopPet()
    private let defaults = UserDefaults.standard
    private let preferencePrefix = CommandLine.arguments.contains("--demo")
        ? "Keytrack.DemoDesktopPet" : "Keytrack.DesktopPet"
    @Published private(set) var isEnabled = false
    private var isClickThrough = false
    @Published private(set) var appearance = DesktopPetAppearance()
    @Published private(set) var wantsGlobalKeys = false
    @Published private(set) var globalKeysActive = false
    private var appearanceWindow: NSWindow?
    private var panel: DesktopPetPanel?
    private var statusItem: NSStatusItem?
    var openWindow: OpenWindowAction?

    private init() {
        isEnabled = defaults.bool(forKey: preferencePrefix + ".Enabled")
        isClickThrough = defaults.bool(forKey: preferencePrefix + ".ClickThrough")
        appearance = DesktopPetAppearance.load(defaults.data(forKey: preferencePrefix + ".Appearance"),
                                               previousCoat: defaults.string(forKey: preferencePrefix + ".Coat"))
        wantsGlobalKeys = defaults.bool(forKey: preferencePrefix + ".GlobalKeys")
        CatSettings.shared.appearance = appearance
    }

    func restore() {
        guard isEnabled, panel == nil else { return }
        let savedOrigin = defaults.string(forKey: preferencePrefix + ".Origin").map(NSPointFromString)
        let window = DesktopPetPanel(origin: savedOrigin, clickThrough: isClickThrough, scale: appearance.scale)
        window.canvas.keyboard.globalStatusChanged = { [weak self] active in self?.globalKeysActive = active }
        window.canvas.didMove = { [weak self] origin in self?.updateSavedOrigin(origin) }
        self.panel = window
        window.orderFrontRegardless()
        window.canvas.start(globalKeys: wantsGlobalKeys)
        createStatusItem()
    }

    private func createStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "cat.fill", accessibilityDescription: "KuroCat 桌宠")
        item.button?.toolTip = "KuroCat 桌宠"
        statusItem = item
        updateMenu()
    }

    private func updateMenu() {
        guard let statusItem else { return }
        let menu = NSMenu()
        menu.addItem(item("打开 Keytrack", action: #selector(showConsole)))
        menu.addItem(item("编辑桌宠外观…", action: #selector(showAppearance)))
        menu.addItem(.separator())
        menu.addItem(item("隐藏 KuroCat 桌宠", action: #selector(hidePet)))
        let clickThrough = item("桌宠鼠标穿透", action: #selector(toggleClickThrough))
        clickThrough.state = isClickThrough ? .on : .off
        menu.addItem(clickThrough)
        let coats = NSMenu()
        for (index, theme) in CatCoatTheme.allCases.enumerated() {
            let option = item(theme.rawValue, action: #selector(selectCoat(_:)))
            option.tag = index
            option.state = theme == appearance.coat ? .on : .off
            coats.addItem(option)
        }
        let coatMenu = NSMenuItem(title: "桌宠皮肤", action: nil, keyEquivalent: "")
        coatMenu.submenu = coats
        menu.addItem(coatMenu)
        menu.addItem(item("桌宠移回屏幕右下角", action: #selector(resetPosition)))
        menu.addItem(.separator())
        menu.addItem(item("退出 Keytrack", action: #selector(quit)))
        statusItem.menu = menu
    }

    private func item(_ title: String, action: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
        item.target = self
        return item
    }

    @objc private func showConsole() {
        if let window = NSApp.windows.first(where: { $0 !== appearanceWindow && $0.canBecomeMain && $0.isVisible }) {
            window.makeKeyAndOrderFront(nil)
        } else {
            openWindow?(id: "console")
        }
        NSApp.activate()
    }

    @objc private func hidePet() { setEnabled(false) }
    @objc private func toggleClickThrough() { setClickThrough(!isClickThrough) }
    @objc private func selectCoat(_ sender: NSMenuItem) {
        var changed = appearance
        changed.coat = CatCoatTheme.allCases[sender.tag]
        setAppearance(changed)
    }

    @objc func showAppearance() {
        if appearanceWindow == nil {
            let host = NSHostingController(rootView: DesktopPetAppearanceView(pet: self))
            let window = NSWindow(contentViewController: host)
            window.title = "KuroCat 桌宠设置"
            window.styleMask = [.titled, .closable]
            window.isReleasedWhenClosed = false
            window.setContentSize(CGSize(width: 480, height: 630))
            window.center()
            appearanceWindow = window
        }
        NSApp.activate()
        appearanceWindow?.makeKeyAndOrderFront(nil)
    }

    func setGlobalKeys(_ enabled: Bool) {
        wantsGlobalKeys = enabled
        defaults.set(enabled, forKey: preferencePrefix + ".GlobalKeys")
        panel?.canvas.keyboard.setGlobal(enabled)
        if enabled && !CGPreflightListenEventAccess() {
            if IOHIDRequestAccess(kIOHIDRequestTypeListenEvent) {
                panel?.canvas.keyboard.setGlobal(true)
            }
        }
    }

    func openInputMonitoring() {
        guard let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent") else { return }
        NSWorkspace.shared.open(url)
    }

    @objc private func quit() { NSApp.terminate(nil) }

    func setEnabled(_ enabled: Bool) {
        isEnabled = enabled
        defaults.set(enabled, forKey: preferencePrefix + ".Enabled")
        if enabled {
            restore()
        } else {
            stop()
        }
    }

    private func setClickThrough(_ enabled: Bool) {
        isClickThrough = enabled
        defaults.set(enabled, forKey: preferencePrefix + ".ClickThrough")
        panel?.canvas.clickThrough = enabled
        panel?.ignoresMouseEvents = true
        updateMenu()
    }

    func setAppearance(_ requested: DesktopPetAppearance) {
        var edited = requested
        edited.normalize()
        let previous = appearance
        guard edited != previous else { return }
        appearance = edited
        if let encoded = try? JSONEncoder().encode(edited) {
            defaults.set(encoded, forKey: preferencePrefix + ".Appearance")
        }
        CatSettings.shared.appearance = edited
        if edited.scale != previous.scale, let panel {
            updateSavedOrigin(panel.resize(to: edited.scale))
        }
        panel?.canvas.needsDisplay = true
        if edited.coat != previous.coat { updateMenu() }
    }

    private func updateSavedOrigin(_ origin: CGPoint) {
        defaults.set(NSStringFromPoint(origin), forKey: preferencePrefix + ".Origin")
    }

    @objc private func resetPosition() {
        defaults.removeObject(forKey: preferencePrefix + ".Origin")
        panel?.moveToVisibleScreen(preferredOrigin: nil)
    }

    func screenConfigurationChanged() {
        guard let panel else { return }
        panel.moveToVisibleScreen(preferredOrigin: panel.frame.origin)
    }

    func stop() {
        panel?.canvas.stop()
        panel?.close()
        panel = nil
        if let statusItem { NSStatusBar.system.removeStatusItem(statusItem) }
        statusItem = nil
    }
}

private final class DesktopPetPanel: NSPanel {
    let canvas: DesktopPetCanvas

    init(origin: CGPoint?, clickThrough: Bool, scale: Double) {
        let size = Self.canvasSize(for: scale)
        canvas = DesktopPetCanvas(frame: CGRect(origin: .zero, size: size))
        super.init(contentRect: canvas.frame, styleMask: [.borderless, .nonactivatingPanel],
                   backing: .buffered, defer: false)
        identifier = NSUserInterfaceItemIdentifier("Keytrack.KuroCat")
        title = "KuroCat 桌宠"
        isReleasedWhenClosed = false
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        hidesOnDeactivate = false
        ignoresMouseEvents = true
        isExcludedFromWindowsMenu = true
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        contentView = canvas
        canvas.autoresizingMask = [.width, .height]
        canvas.clickThrough = clickThrough
        moveToVisibleScreen(preferredOrigin: origin)
    }

    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    private static func canvasSize(for scale: Double) -> CGSize {
        CGSize(width: CatPhysics.canvasSize.width * scale, height: CatPhysics.canvasSize.height * scale)
    }

    func resize(to scale: Double) -> CGPoint {
        let size = Self.canvasSize(for: scale)
        let current = frame
        let origin = CGPoint(x: current.maxX - size.width, y: current.minY)
        setFrame(CGRect(origin: origin, size: size), display: true)
        moveToVisibleScreen(preferredOrigin: origin)
        return frame.origin
    }

    func moveToVisibleScreen(preferredOrigin: CGPoint?) {
        let preferredFrame = preferredOrigin.map { CGRect(origin: $0, size: frame.size) }
        let screen = NSScreen.screens.first { screen in
            preferredFrame.map { screen.visibleFrame.contains(CGPoint(x: $0.midX, y: $0.midY)) } ?? false
        } ?? NSScreen.main
        guard let visible = screen?.visibleFrame else { return }
        let fallback = CGPoint(x: visible.maxX - frame.width - 16, y: visible.minY + 12)
        let origin = preferredFrame.map { visible.intersects($0) ? $0.origin : fallback } ?? fallback
        setFrameOrigin(CGPoint(
            x: max(visible.minX, min(origin.x, visible.maxX - frame.width)),
            y: max(visible.minY, min(origin.y, visible.maxY - frame.height))
        ))
    }
}

struct DesktopPetInput {
    let pointer: CGPoint
    let keyDowns: UInt32
    let leftClicks: UInt32
    let rightClicks: UInt32
    let buttons: Int
    let secureInput: Bool

    static func system() -> Self {
        let state = CGEventSourceStateID.combinedSessionState
        return Self(
            pointer: NSEvent.mouseLocation,
            keyDowns: CGEventSource.counterForEventType(state, eventType: .keyDown),
            leftClicks: CGEventSource.counterForEventType(state, eventType: .leftMouseDown),
            rightClicks: CGEventSource.counterForEventType(state, eventType: .rightMouseDown),
            buttons: NSEvent.pressedMouseButtons,
            secureInput: IsSecureEventInputEnabled()
        )
    }
}

struct DesktopPetActivity {
    private var previous: DesktopPetInput
    private var lastMouseMove: CFTimeInterval
    private var lastMouseClick: CFTimeInterval = 0
    private var lastKeyPress: CFTimeInterval = 0
    private var keysPerMinute: CGFloat = 0
    private var nextBeat: PhysicalKey = .f

    init(initial: DesktopPetInput, now: CFTimeInterval) {
        previous = initial
        lastMouseMove = now
    }

    mutating func advance(
        _ sample: DesktopPetInput, now: CFTimeInterval, dt: CGFloat, physics: CatPhysics,
        exactKeys: [PhysicalKey]? = nil
    ) -> CatFrameInput {
        let keyDelta = sample.keyDowns &- previous.keyDowns
        let presses = exactKeys == nil && !sample.secureInput && !previous.secureInput && keyDelta <= 600 ? keyDelta : 0
        keysPerMinute *= exp(-dt / 2)
        if presses > 0 {
            // Animate a paw without lighting an arbitrary key.
            physics.triggerKeyDown(nextBeat, at: now, highlightKey: false)
            nextBeat = nextBeat == .f ? .j : .f
            registerKeyPress(count: presses, at: now)
        }

        let dx = sample.pointer.x - previous.pointer.x
        let dy = sample.pointer.y - previous.pointer.y
        if dx != 0 || dy != 0 { lastMouseMove = now }
        if sample.leftClicks != previous.leftClicks || sample.rightClicks != previous.rightClicks
            || sample.buttons & ~previous.buttons != 0 {
            lastMouseClick = now
        }
        for button in 0..<3 {
            let mask = 1 << button
            let down = sample.buttons & mask != 0
            let wasDown = previous.buttons & mask != 0
            let clicked = (button == 0 && sample.leftClicks != previous.leftClicks)
                || (button == 1 && sample.rightClicks != previous.rightClicks)
            if clicked || down != wasDown {
                physics.triggerMouseClick(button: button, isDown: clicked || down)
                if clicked && !down {
                    // Show fast clicks that start and finish between two frames.
                    physics.triggerMouseClick(button: button, isDown: false)
                }
            }
        }
        previous = sample
        let heldKeys = sample.secureInput ? [] : exactKeys ?? []
        return CatFrameInput(
            now: now, activeKeys: Set(heldKeys), orderedKeys: heldKeys, mouseScreenPos: sample.pointer,
            mouseVelocity: CGVector(dx: dx / dt, dy: dy / dt),
            leftMouseDown: sample.buttons & 1 != 0, rightMouseDown: sample.buttons & 2 != 0,
            otherMouseDown: sample.buttons & 4 != 0, lastMouseMoveTime: lastMouseMove,
            lastMouseClickTime: lastMouseClick, lastKeyActivityTime: lastKeyPress,
            keysPerMinute: keysPerMinute
        )
    }

    mutating func registerKeyPress(count: UInt32 = 1, at now: CFTimeInterval) {
        lastKeyPress = now
        keysPerMinute = min(600, keysPerMinute + CGFloat(count) * 30)
    }
}

private final class DesktopPetCanvas: NSView {
    private let physics = CatPhysics()
    lazy var keyboard = DesktopPetKeyboard(press: { [weak self] key in
        guard let self else { return }
        let now = CACurrentMediaTime()
        self.physics.triggerKeyDown(key, at: now)
        self.activity?.registerKeyPress(at: now)
        self.needsDisplay = true
    }, clearFeedback: { [weak self] in self?.physics.clearKeyFeedback() })
    private var activity: DesktopPetActivity?
    private var ticker: Timer?
    private var lastFrame: CFTimeInterval = 0
    private var lastPetPoint: CGPoint?
    private var dragging = false
    var clickThrough = false
    var didMove: ((CGPoint) -> Void)?

    override var isFlipped: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    func start(globalKeys: Bool) {
        let now = CACurrentMediaTime()
        activity = DesktopPetActivity(initial: .system(), now: now)
        keyboard.start(global: globalKeys)
        lastFrame = now
        schedule(every: 1.0 / 30)
    }

    func stop() {
        ticker?.invalidate()
        ticker = nil
        keyboard.stop()
        activity = nil
    }

    private func schedule(every interval: TimeInterval) {
        ticker?.invalidate()
        let timer = Timer(timeInterval: interval, target: self, selector: #selector(tick), userInfo: nil, repeats: true)
        timer.tolerance = interval * 0.1
        ticker = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    @objc private func tick() {
        guard let window, window.isVisible else { return }
        let now = CACurrentMediaTime()
        let dt = max(1.0 / 120, now - lastFrame)
        lastFrame = now
        let sample = DesktopPetInput.system()
        let exactKeys = keyboard.frameKeys(secureInput: sample.secureInput, now: now)
        guard let input = activity?.advance(sample, now: now, dt: dt, physics: physics,
                                            exactKeys: exactKeys) else { return }
        updateHover(at: sample.pointer, window: window)
        physics.step(dt: dt, windowFrameInScreen: window.frame, input: input)
        needsDisplay = true

        let lastActivity = max(input.lastKeyActivityTime, input.lastMouseMoveTime, input.lastMouseClickTime)
        let interval = now - lastActivity < 4 ? 1.0 / 30 : 1.0 / 10
        if ticker?.timeInterval != interval { schedule(every: interval) }
    }

    private func updateHover(at pointer: CGPoint, window: NSWindow) {
        guard !dragging else { return }
        let frame = window.frame
        let canvasPoint = CGPoint(x: (pointer.x - frame.minX) * CatPhysics.canvasSize.width / frame.width,
                                  y: (frame.maxY - pointer.y) * CatPhysics.canvasSize.height / frame.height)
        let settings = CatSettings.shared
        let point = CatRenderer.canvasPointToCatSpace(canvasPoint, flipped: settings.flipHorizontal,
                                                      rotationDeg: settings.rotationDeg)
        let zone = !clickThrough && frame.contains(pointer)
            ? CatRenderer.hitTest(point: point, physics: physics, showPermissionPill: false) : .none
        let ignore = zone == .none
        if window.ignoresMouseEvents != ignore { window.ignoresMouseEvents = ignore }
        if zone == .head, let previous = lastPetPoint {
            let delta = hypot(point.x - previous.x, point.y - previous.y)
            if delta > 1.2 && delta < 80 {
                physics.registerPetStroke(canvasPoint: point, delta: delta, isHead: true)
            }
        }
        lastPetPoint = zone == .head ? point : nil
        physics.updateTailHover(canvasPoint: zone == .none ? nil : point)
    }

    override func mouseDown(with event: NSEvent) {
        guard !clickThrough, let window else { return }
        dragging = true
        lastPetPoint = nil
        physics.setDragging(true)
        window.performDrag(with: event)
        physics.setDragging(false)
        dragging = false
        didMove?(window.frame.origin)
    }

    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        context.clear(bounds)
        context.saveGState()
        context.scaleBy(x: bounds.width / CatPhysics.canvasSize.width,
                        y: bounds.height / CatPhysics.canvasSize.height)
        CatRenderer.draw(in: context, physics: physics, showPermissionPill: false)
        context.restoreGState()
    }
}
