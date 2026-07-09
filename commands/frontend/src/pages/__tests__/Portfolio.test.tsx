import Portfolio from "../Portfolio"
describe("Portfolio page", () => {
  it("can be imported", () => {
    expect(Portfolio).toBeDefined()
    expect(typeof Portfolio).toBe("function")
  })
})