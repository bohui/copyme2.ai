/** Resolve native dynamic imports through Jest's module registry in fixture tests. */
module.exports = ({ types: t }) => ({
  visitor: {
    CallExpression(path) {
      if (path.node.callee.type !== "Import") return;
      const source = path.node.arguments[0];
      path.replaceWith(
        t.callExpression(
          t.memberExpression(
            t.callExpression(
              t.memberExpression(
                t.identifier("Promise"),
                t.identifier("resolve"),
              ),
              [],
            ),
            t.identifier("then"),
          ),
          [
            t.arrowFunctionExpression(
              [],
              t.callExpression(t.identifier("require"), [source]),
            ),
          ],
        ),
      );
    },
  },
});
