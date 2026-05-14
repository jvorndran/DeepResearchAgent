export {};

const STREAM_FIXTURE_JOB_ID = 'chart_family_audit';
const CHART_MARK_SELECTOR = [
  '.recharts-line-curve',
  '.recharts-bar-rectangle',
  '.recharts-bar-rectangle path',
  '.recharts-area-area',
  '.recharts-scatter-symbol',
  '.recharts-symbols',
  '.recharts-pie-sector',
  '.recharts-pie-sector path',
  '.recharts-radar-polygon',
  '.recharts-radial-bar-sector',
  '.recharts-radial-bar-sector path',
  '.recharts-funnel-trapezoid',
  '.recharts-funnel-trapezoid path',
  '.recharts-treemap-depth-1',
  '.recharts-treemap-depth-1 rect',
  '.recharts-sankey-link',
  '.recharts-sankey-link path',
  '.recharts-sunburst-sector',
  '.recharts-sunburst-sector path',
  '.recharts-sunburst .recharts-sector',
  '.recharts-sunburst path',
].join(', ');
const RECHARTS_SIZE_WARNING_PATTERN = /\b(?:width|height)\(-?\d+(?:\.\d+)?\)/;

function loadAuditReport(): Cypress.Chainable<Record<string, unknown>> {
  const reportPath = Cypress.env('REPORT_JSON_PATH') as string | undefined;
  if (reportPath) {
    return cy.readFile(reportPath);
  }
  return cy.fixture('report-all-chart-families.json');
}

describe('chart render audit', () => {
  it('renders report charts without contract errors or invalid SVG attributes', () => {
    loadAuditReport().then((report) => {
      const expectedChartCount = Object.keys((report.charts as Record<string, unknown> | undefined) ?? {}).length;
      const rechartsSizingWarnings: string[] = [];

      cy.intercept('GET', '/api/backend/api/reports/*', {
        body: report,
      }).as('getReport');

      cy.visit(`/chart-render-audit/${STREAM_FIXTURE_JOB_ID}`, {
        onBeforeLoad(win) {
          win.sessionStorage.setItem(
            'pending_messages',
            JSON.stringify([{ role: 'user', content: String(report.query ?? 'Render chart report') }]),
          );
          win.localStorage.setItem('__cypress_stream_scenario__', 'research');

          const originalWarn = win.console.warn.bind(win.console);
          win.console.warn = (...args) => {
            const message = args.map(String).join(' ');
            if (RECHARTS_SIZE_WARNING_PATTERN.test(message)) {
              rechartsSizingWarnings.push(message);
            }
            originalWarn(...args);
          };
        },
      });

      cy.wait('@getReport', { timeout: 120000 });
      cy.get('[data-testid="report-view"]').should('exist');
      cy.get('[data-testid="chart-render-contract-error"]').should('not.exist');
      cy.get('.recharts-wrapper').should('have.length', expectedChartCount);
      cy.get('.recharts-wrapper').each(($wrapper, index) => {
        cy.wrap($wrapper).scrollIntoView({ duration: 0 });
        cy.wrap($wrapper).should(($chartWrapper) => {
          const rect = $chartWrapper[0].getBoundingClientRect();
          expect(rect.width, `chart ${index + 1} wrapper width`).to.be.greaterThan(0);
          expect(rect.height, `chart ${index + 1} wrapper height`).to.be.greaterThan(0);
        });
        cy.wrap($wrapper).find('svg').should(($svg) => {
          expect($svg.length, `chart ${index + 1} svg`).to.be.greaterThan(0);
          const rect = $svg[0].getBoundingClientRect();
          expect(rect.width, `chart ${index + 1} svg width`).to.be.greaterThan(0);
          expect(rect.height, `chart ${index + 1} svg height`).to.be.greaterThan(0);
        });
        cy.wrap($wrapper).should(($chartWrapper) => {
          const marks = Array.from($chartWrapper[0].querySelectorAll(CHART_MARK_SELECTOR));
          const visibleMarks = marks.filter((mark) => {
            const style = getComputedStyle(mark);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
              return false;
            }
            const svgMark = mark as SVGGraphicsElement;
            if (typeof svgMark.getBBox === 'function') {
              try {
                const box = svgMark.getBBox();
                return box.width + box.height > 0;
              } catch {
                return false;
              }
            }
            const rect = mark.getBoundingClientRect();
            return rect.width + rect.height > 0;
          });
          const rechartsClasses = Array.from(
            new Set(
              Array.from($chartWrapper[0].querySelectorAll('[class*="recharts"]'))
                .map((node) => node.getAttribute('class'))
                .filter(Boolean),
            ),
          ).slice(0, 20);
          expect(
            visibleMarks.length,
            `visible marks in chart ${index + 1}; Recharts classes: ${rechartsClasses.join(' | ')}`,
          ).to.be.greaterThan(0);
        });
      });
      cy.get('.recharts-wrapper svg').each(($svg) => {
        const markup = $svg.prop('outerHTML');
        expect(markup).not.to.match(/\b(?:NaN|Infinity|-Infinity)\b/);
      });
      cy.then(() => {
        expect(rechartsSizingWarnings, 'Recharts sizing warnings').to.deep.equal([]);
      });
    });
  });
});
