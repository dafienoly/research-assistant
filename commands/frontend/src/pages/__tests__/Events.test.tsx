import Events from "../Events"
describe("Events page", () => {
  it("can be imported", () => {
    expect(Events).toBeDefined()
    expect(typeof Events).toBe("function")
  })
})