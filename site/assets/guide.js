// 正文已在 HTML 中完整输出；脚本只同步目录高亮，不参与加载和切换章节。
const guide = document.querySelector('.guide');
if (guide) {
  const sections = [...guide.querySelectorAll('.guide-section')];
  const links = [...guide.querySelectorAll('.steps a')];
  let scheduled = false;
  const update = () => {
    scheduled = false;
    const boundary = guide.querySelector('.steps').getBoundingClientRect().top + 100;
    let current = 0;
    sections.forEach((section, i) => {
      if (section.getBoundingClientRect().top <= boundary) current = i;
    });
    links.forEach((link, i) => {
      link.parentElement.classList.toggle('now', i === current);
      link.parentElement.classList.toggle('done', i < current);
      if (i === current) link.setAttribute('aria-current', 'step');
      else link.removeAttribute('aria-current');
    });
  };
  const schedule = () => {
    if (!scheduled) { scheduled = true; requestAnimationFrame(update); }
  };
  addEventListener('scroll', schedule, { passive: true });
  addEventListener('resize', schedule, { passive: true });
  addEventListener('hashchange', schedule);
  addEventListener('load', schedule);
  update();
}
