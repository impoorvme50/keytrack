import AppKit

@main struct DesktopPetTests {
    static func main() {
        let physics = CatPhysics()
        func sample(_ keys: UInt32, secure: Bool = false, pointer: CGPoint = .zero,
                    clicks: UInt32 = 0, buttons: Int = 0) -> DesktopPetInput {
            DesktopPetInput(pointer: pointer, keyDowns: keys, leftClicks: clicks, rightClicks: 0,
                            buttons: buttons, secureInput: secure)
        }

        let frame = CGRect(x: 0, y: 0, width: 252, height: 224)
        var activity = DesktopPetActivity(initial: sample(300), now: 10)
        let idle = activity.advance(sample(300), now: 10.1, dt: 0.1, physics: physics)
        precondition(idle.lastKeyActivityTime == 0 && physics.keyGlow.isEmpty)

        let typing = activity.advance(sample(301), now: 10.2, dt: 0.1, physics: physics)
        physics.step(dt: 0.1, windowFrameInScreen: frame, input: typing)
        precondition(typing.lastKeyActivityTime == 10.2 && typing.keysPerMinute > 0)
        precondition(typing.activeKeys.isEmpty && typing.orderedKeys.isEmpty)
        precondition(physics.rightPawTyping && physics.floatingKeycaps.isEmpty)
        precondition(physics.keyGlow.isEmpty, "Anonymous activity must not light a specific key")

        let secure = activity.advance(sample(302, secure: true), now: 10.3, dt: 0.1, physics: physics)
        precondition(secure.lastKeyActivityTime == typing.lastKeyActivityTime)
        let unlocked = activity.advance(sample(310), now: 10.4, dt: 0.1, physics: physics)
        precondition(unlocked.lastKeyActivityTime == typing.lastKeyActivityTime)
        let resumed = activity.advance(sample(311), now: 10.5, dt: 0.1, physics: physics)
        physics.step(dt: 0.1, windowFrameInScreen: frame, input: resumed)
        precondition(resumed.lastKeyActivityTime == 10.5 && physics.leftPawTyping)

        let reset = activity.advance(sample(10), now: 10.6, dt: 0.1, physics: physics)
        precondition(reset.lastKeyActivityTime == resumed.lastKeyActivityTime)
        let mouse = activity.advance(sample(10, pointer: CGPoint(x: 40, y: 20), clicks: 1),
                                     now: 10.7, dt: 0.1, physics: physics)
        precondition(mouse.mouseVelocity == CGVector(dx: 400, dy: 200))
        precondition(mouse.lastMouseClickTime == 10.7 && mouse.lastMouseMoveTime == 10.7)
        precondition(!mouse.leftMouseDown && physics.mousePressLeft.value > 0)

        var wrapped = DesktopPetActivity(initial: sample(.max), now: 11)
        let next = wrapped.advance(sample(0), now: 11.1, dt: 0.1, physics: CatPhysics())
        precondition(next.lastKeyActivityTime == 11.1)

        var exact = DesktopPetKeys()
        precondition(exact.apply(.keyDown, code: 0, flags: []) == .a)
        precondition(exact.apply(.keyDown, code: 0, flags: []) == nil)
        precondition(exact.apply(.keyDown, code: 124, flags: []) == .arrowRight)
        precondition(exact.apply(.flagsChanged, code: 56, flags: [.maskShift, CGEventFlags(rawValue: 2)]) == .leftShift)
        precondition(exact.apply(.flagsChanged, code: 60, flags: [.maskShift, CGEventFlags(rawValue: 6)]) == .rightShift)
        precondition(exact.ordered == [.a, .arrowRight, .leftShift, .rightShift])
        precondition(exact.apply(.flagsChanged, code: 56, flags: [.maskShift, CGEventFlags(rawValue: 4)]) == nil)
        precondition(exact.ordered == [.a, .arrowRight, .rightShift])
        _ = exact.apply(.keyUp, code: 0, flags: [])
        _ = exact.apply(.keyUp, code: 124, flags: [])
        _ = exact.apply(.flagsChanged, code: 60, flags: [])
        precondition(exact.ordered.isEmpty)

        let realPhysics = CatPhysics()
        let heldKeys: [PhysicalKey] = [.a, .arrowRight]
        var real = DesktopPetActivity(initial: sample(500), now: 20)
        for key in heldKeys {
            realPhysics.triggerKeyDown(key, at: 20.1)
            real.registerKeyPress(at: 20.1)
        }
        let realFrame = real.advance(sample(502), now: 20.2, dt: 0.1, physics: realPhysics, exactKeys: heldKeys)
        realPhysics.step(dt: 0.1, windowFrameInScreen: frame, input: realFrame)
        precondition(realFrame.orderedKeys == heldKeys && realFrame.lastKeyActivityTime == 20.1)
        precondition(realPhysics.keyGlow[.a] == 1 && realPhysics.keyGlow[.arrowRight] == 1 && realPhysics.keyGlow[.f] == nil)
        let secureFrame = real.advance(sample(502, secure: true), now: 20.3, dt: 0.1, physics: realPhysics, exactKeys: heldKeys)
        precondition(secureFrame.activeKeys.isEmpty && secureFrame.orderedKeys.isEmpty)
        realPhysics.clearKeyFeedback()
        precondition(realPhysics.keyGlow.isEmpty)

        let previous = DesktopPetAppearance.load(nil, previousCoat: CatCoatTheme.shorthair.rawValue)
        precondition(previous.coat == .shorthair)
        var appearance = DesktopPetAppearance(keyboard: .retroCream, furRGB: 0xC54680,
                                              irisRGB: 0x338BDD, scale: 1.5, rotation: 40, mirrored: true)
        appearance.normalize()
        precondition(appearance.scale == 1.3 && appearance.rotation == 30)
        precondition(appearance.skin.palette.body == .hex(0xC54680))
        precondition(appearance.skin.palette.tail == .hex(0xC54680))
        precondition(appearance.skin.palette.irisLeft == .hex(0x338BDD))
        let encoded = try! JSONEncoder().encode(appearance)
        precondition(DesktopPetAppearance.load(encoded, previousCoat: nil) == appearance)
        print("KuroCat exact and anonymous key feedback, secure input, mouse and appearance checks passed")
    }
}
