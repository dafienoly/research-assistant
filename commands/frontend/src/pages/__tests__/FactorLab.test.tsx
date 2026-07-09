import FactorLab from "../FactorLab"
describe("FactorLab page", () => {
  it("can be imported", () => {
    expect(FactorLab).toBeDefined()
    expect(typeof FactorLab).toBe("function")
  })
})