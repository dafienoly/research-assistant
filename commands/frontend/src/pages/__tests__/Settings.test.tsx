import Settings from "../Settings"
describe("Settings page", () => {
  it("can be imported", () => {
    expect(Settings).toBeDefined()
    expect(typeof Settings).toBe("function")
  })
})