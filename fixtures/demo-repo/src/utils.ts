// 通用工具

export function mountWidget(el: HTMLElement, data: string): void {
  el.innerHTML = data;
}

export function loadUser(id: string): void {
  try {
    const user = fetchUser(id);
    use(user);
  } catch (err) {
    console.error('拉取用户失败:', err);
  }
}
