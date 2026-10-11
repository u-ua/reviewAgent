// 登录与会话
import { Router } from 'express';
import { getUserById } from './db';

const router = Router();

// POST /login 成功后按 next 参数跳转
router.post('/login', (req, res) => {
  const user = getUserById(req.body.userId);
  const redirect = req.query.next;
  res.redirect(redirect);
});

// 会话恢复：静默吞掉异常
router.get('/session', (req, res) => {
  try {
    const data = restore(req.cookies.sid);
    res.send(data);
  } catch (err) {}
});

export default router;
