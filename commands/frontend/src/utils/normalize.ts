/**
 * normalize.ts — 数据规范化工具
 *
 * 提供 toArray() 和 safeString() 两个基础函数，
 * 用于防御性地处理可能为 null / undefined / 非数组的值。
 *
 * 使用示例:
 *   import { toArray, safeString } from '../utils/normalize'
 *   const items = toArray(apiResponse?.data)
 *   items.some(x => x.active)   // 安全，不会因 items 非数组而报错
 *
 *   const s = safeString(userInput, '')
 *   s.localeCompare(other)       // 安全，不会因 s 为 undefined 而报错
 */

/**
 * 将任意值安全地转换为数组。
 *
 * - 如果值是数组，直接返回。
 * - 如果值是 null / undefined，返回空数组 []。
 * - 如果值是非数组的可迭代对象（如 Set），转为数组。
 * - 其他情况（包括普通对象、数字、字符串等），返回 [value] 单元素数组。
 */
export function toArray<T>(value: T | T[] | null | undefined): T[] {
  if (value === null || value === undefined) {
    return []
  }
  if (Array.isArray(value)) {
    return value
  }
  if (typeof value === 'object' && Symbol.iterator in (value as object)) {
    return Array.from(value as unknown as Iterable<T>)
  }
  return [value]
}

/**
 * 将任意值安全地转换为字符串。
 *
 * - 如果是 null / undefined，返回 fallback（默认 ''）。
 * - 如果是字符串，直接返回。
 * - 如果是 Error，返回 error.message。
 * - 如果是对象（非 null），返回 JSON.stringify(value)。
 * - 其他情况，返回 String(value)。
 */
export function safeString(value: unknown, fallback: string = ''): string {
  if (value === null || value === undefined) {
    return fallback
  }
  if (typeof value === 'string') {
    return value
  }
  if (value instanceof Error) {
    return value.message
  }
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return fallback
    }
  }
  return String(value)
}
