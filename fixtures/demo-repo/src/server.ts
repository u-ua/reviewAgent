// 演示仓库：一个玩具 Express 服务，预埋若干普通代码缺陷供审查
import { Router } from 'express';
import { getUsersByCompany } from './db';
import { mountWidget } from './utils';

const router = Router();

// GET /users?company=acme —— 用字符串拼接 SQL，存在注入风险
router.get('/users', (req, res) => {
  const company = req.query.company;
  const sql = "SELECT * FROM users WHERE company = '" + company + "'";
  const rows = getUsersByCompany(sql);
  res.send(rows.join(','));
});

// GET /hello?name=x —— 未校验就直接回显用户输入
router.get('/hello', (req, res) => {
  const name = req.query.name;
  res.send('<div>你好，' + req.query.name + '</div>');
});

export default router;
