const workerLoaderFlags = new Set(["--require", "-r", "--import", "--loader", "--experimental-loader"]);
const workerLoaderPrefixes = ["--require=", "--import=", "--loader=", "--experimental-loader="];

export function getWorkerExecArgv(argumentsList = process.execArgv) {
  const filtered: string[] = [];

  for (let index = 0; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index];
    if (workerLoaderPrefixes.some((prefix) => argument.startsWith(prefix))) {
      filtered.push(argument);
      continue;
    }
    if (!workerLoaderFlags.has(argument)) {
      continue;
    }

    const value = argumentsList[index + 1];
    if (value && !value.startsWith("--")) {
      filtered.push(argument, value);
      index += 1;
    }
  }

  return filtered;
}
