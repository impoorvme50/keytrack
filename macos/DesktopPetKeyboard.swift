import AppKit
import Carbon

struct DesktopPetKeys {
    private var codes: [UInt16] = []

    var ordered: [PhysicalKey] {
        var seen = Set<PhysicalKey>()
        return codes.compactMap(PhysicalKey.fromCGKeyCode).filter { seen.insert($0).inserted }
    }

    mutating func apply(_ type: CGEventType, code: UInt16, flags: CGEventFlags) -> PhysicalKey? {
        guard let key = PhysicalKey.fromCGKeyCode(code) else { return nil }
        let isDown: Bool
        switch type {
        case .keyDown: isDown = true
        case .keyUp: isDown = false
        case .flagsChanged:
            if key == .capsLock { return key }
            guard let down = modifierIsDown(key, flags: flags) else { return nil }
            isDown = down
        default: return nil
        }
        if isDown && !codes.contains(code) {
            codes.append(code)
            return key
        }
        if !isDown { codes.removeAll { $0 == code } }
        return nil
    }

    mutating func clear() { codes.removeAll() }

    private func modifierIsDown(_ key: PhysicalKey, flags: CGEventFlags) -> Bool? {
        // Device-dependent bits distinguish the left and right keys of a held modifier.
        let sides: (CGEventFlags, UInt64, UInt64)
        switch key {
        case .leftShift: sides = (.maskShift, 0x06, 0x02)
        case .rightShift: sides = (.maskShift, 0x06, 0x04)
        case .leftControl: sides = (.maskControl, 0x2001, 0x01)
        case .rightControl: sides = (.maskControl, 0x2001, 0x2000)
        case .leftOption: sides = (.maskAlternate, 0x60, 0x20)
        case .rightOption: sides = (.maskAlternate, 0x60, 0x40)
        case .leftCommand: sides = (.maskCommand, 0x18, 0x08)
        case .rightCommand: sides = (.maskCommand, 0x18, 0x10)
        case .fn: return flags.contains(.maskSecondaryFn)
        default: return nil
        }
        return flags.contains(sides.0) &&
            (flags.rawValue & sides.1 == 0 || flags.rawValue & sides.2 != 0)
    }
}

@MainActor final class DesktopPetKeyboard {
    private var keys = DesktopPetKeys()
    private var localMonitor: Any?
    private var globalTap: CFMachPort?
    private var tapSource: CFRunLoopSource?
    private var hadFocus = false
    private var wasSecure = false
    private var lastAccessCheck: CFTimeInterval = -.infinity
    private var wantsGlobal = false
    private let press: (PhysicalKey) -> Void
    private let clearFeedback: () -> Void
    var globalStatusChanged: ((Bool) -> Void)?

    init(press: @escaping (PhysicalKey) -> Void, clearFeedback: @escaping () -> Void) {
        self.press = press
        self.clearFeedback = clearFeedback
    }

    func start(global: Bool) {
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .keyUp, .flagsChanged]) { [weak self] event in
            guard let self, self.globalTap == nil else { return event }
            let type: CGEventType
            switch event.type {
            case .keyDown: type = .keyDown
            case .keyUp: type = .keyUp
            case .flagsChanged: type = .flagsChanged
            default: return event
            }
            self.receive(type, code: event.keyCode, flags: CGEventFlags(rawValue: UInt64(event.modifierFlags.rawValue)))
            return event
        }
        setGlobal(global)
    }

    func setGlobal(_ enabled: Bool) {
        wantsGlobal = enabled
        if enabled {
            lastAccessCheck = -.infinity
            refreshGlobal(at: CACurrentMediaTime())
        } else {
            stopGlobal()
        }
    }

    /// nil means that this frame should use the anonymous activity animation.
    func frameKeys(secureInput: Bool, now: CFTimeInterval) -> [PhysicalKey]? {
        refreshGlobal(at: now)
        let focused = NSApp.isActive
        if (secureInput && !wasSecure) || (hadFocus && !focused && globalTap == nil) {
            clearKeys()
        }
        wasSecure = secureInput
        hadFocus = focused
        guard !secureInput, focused || globalTap != nil else { return nil }
        return keys.ordered
    }

    func stop() {
        if let localMonitor { NSEvent.removeMonitor(localMonitor) }
        localMonitor = nil
        wantsGlobal = false
        stopGlobal()
        clearKeys()
    }

    private func clearKeys() {
        keys.clear()
        clearFeedback()
    }

    private func receive(_ type: CGEventType, code: UInt16, flags: CGEventFlags) {
        guard !IsSecureEventInputEnabled() else {
            clearKeys()
            return
        }
        if let key = keys.apply(type, code: code, flags: flags) { press(key) }
    }

    private func refreshGlobal(at now: CFTimeInterval) {
        guard wantsGlobal, now - lastAccessCheck >= 2 else { return }
        lastAccessCheck = now
        guard CGPreflightListenEventAccess() else {
            stopGlobal()
            return
        }
        if let globalTap {
            if !CGEvent.tapIsEnabled(tap: globalTap), !IsSecureEventInputEnabled() {
                CGEvent.tapEnable(tap: globalTap, enable: true)
            }
            return
        }

        let eventTypes: [CGEventType] = [.keyDown, .keyUp, .flagsChanged]
        let mask = eventTypes.reduce(CGEventMask(0)) { $0 | (1 << $1.rawValue) }
        // Source runs on the main run loop. Only a mapped key position reaches the view.
        guard let tap = CGEvent.tapCreate(tap: .cgSessionEventTap, place: .tailAppendEventTap,
            options: .listenOnly, eventsOfInterest: mask, callback: { _, type, event, reference in
                guard let reference else { return Unmanaged.passUnretained(event) }
                let keyboard = Unmanaged<DesktopPetKeyboard>.fromOpaque(reference).takeUnretainedValue()
                MainActor.assumeIsolated {
                    switch type {
                    case .tapDisabledByTimeout, .tapDisabledByUserInput:
                        keyboard.clearKeys()
                    case .keyDown, .keyUp, .flagsChanged:
                        let code = event.getIntegerValueField(.keyboardEventKeycode)
                        if let keyCode = UInt16(exactly: code) {
                            keyboard.receive(type, code: keyCode, flags: event.flags)
                        }
                    default: break
                    }
                }
                return Unmanaged.passUnretained(event)
            }, userInfo: Unmanaged.passUnretained(self).toOpaque()),
            let source = CFMachPortCreateRunLoopSource(nil, tap, 0) else { return }
        clearKeys()
        globalTap = tap
        tapSource = source
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)
        globalStatusChanged?(true)
    }

    private func stopGlobal() {
        guard let globalTap else { return }
        CGEvent.tapEnable(tap: globalTap, enable: false)
        if let tapSource { CFRunLoopRemoveSource(CFRunLoopGetMain(), tapSource, .commonModes) }
        CFMachPortInvalidate(globalTap)
        self.globalTap = nil
        tapSource = nil
        clearKeys()
        globalStatusChanged?(false)
    }
}
