import app from "./app";

const PORT = 3330;

function server() {
  app.listen(PORT, () => {
    console.log(`Server running on PORT: http://localhost:${PORT}`);
  });
}

server();
