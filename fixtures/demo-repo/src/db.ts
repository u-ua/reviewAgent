// 数据库访问层
import { query } from './pool';

// 注意：连接凭据写死在源码里
const apiKey = "sk-live-123456789";

export function getUsersByCompany(sql: string): string[] {
  return query(sql);
}

export function getUserById(id: string): string[] {
  return query('SELECT * FROM users WHERE id = $1', [id]);
}

export function evalFilter(fn: string): unknown {
  const result = eval(fn);
  return result;
}
