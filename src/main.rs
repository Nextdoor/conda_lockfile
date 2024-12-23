extern crate clap;
extern crate glob;
extern crate sha1;
extern crate tempfile;
extern crate yaml_rust;
#[macro_use]
extern crate log;
extern crate simplelog;

use std::collections::HashSet;
use std::env;
use std::error::Error;
use std::fs::{copy, File};
use std::io::prelude::*;
use std::io::Result as ioResult;
use std::io::{Error as ioError, ErrorKind as ioErrorKind};
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::str;

use clap::{App, Arg, ArgMatches, SubCommand};
use glob::glob;
use simplelog::{Config, LogLevelFilter, SimpleLogger, TermLogger};
use tempfile::tempdir_in;
use yaml_rust::{Yaml, YamlEmitter, YamlLoader};

const SIGIL: &str = "# ENVHASH:";
const VERSION: &'static str = env!("CARGO_PKG_VERSION");

type Result<T> = std::result::Result<T, Box<dyn Error>>;

const DOCKERFILE: &str = "
FROM debian:stretch

RUN mkdir /app
WORKDIR /app
ENV CONDA_ROOT /var/lib/conda

RUN apt-get update && \
    apt-get install --yes bzip2 coreutils curl libc6 libc6-dev libc-dev gcc g++ net-tools && \
    apt-get autoclean

RUN curl https://repo.anaconda.com/miniconda/Miniconda3-py37_4.8.2-Linux-x86_64.sh > miniconda.sh
RUN bash miniconda.sh -b -f -p $CONDA_ROOT
RUN echo 'ONE_LINE_COMMAND' > build_lockfile.sh

ENTRYPOINT [\"/bin/bash\", \"./build_lockfile.sh\"]
";

const BUILD_LOCKFILE: &str = "set -e
cd artifacts
# We need the name of the environment for exporting the environment.
# Unfortunately, `conda env create` doesn't return any information identifying
# the name of the environment it created. As a workaround, provide an explicit
# name to `conda env create` so there is no ambiguity when calling `conda env
# export`.  This name *ought* be what is specified in `env.yml` itself.
ENV_NAME=$(cat env_name)
$CONDA_ROOT/bin/conda env create -f deps.yml -n $ENV_NAME
# The prefix line includes an absolute path from inside this container.
# Remove it to avoid confusion.
$CONDA_ROOT/bin/conda env export -n $ENV_NAME | grep -v \"^prefix:\" > deps.lock.yml
";

fn interpolate_dockerfile() -> String {
    let one_line_command: Vec<&str> = BUILD_LOCKFILE
        .lines()
        .filter(|line| !line.starts_with("#"))
        .collect();
    let olc = one_line_command.join(";");
    DOCKERFILE.replace("ONE_LINE_COMMAND", &olc)
}

fn get_app<'a, 'b>(default_platform: &'a str) -> App<'a, 'b> {
    App::new("conda-lockfile")
        .about("An application dependency workflow manager for conda")
        .version(VERSION)
        .arg(
            Arg::with_name("v")
                .short("v")
                .multiple(true)
                .global(true)
                .help("Sets the level of verbosity"),
        ).subcommand(
            SubCommand::with_name("freeze")
                .about("Freeze abstract dependencies into a lockfile")
                .arg(
                    Arg::with_name("depfile")
                        .short("d")
                        .long("depfile")
                        .default_value("deps.yml")
                        .help("Freeze dependencies from this depfile"),
                )
                .arg(
                    Arg::with_name("platform")
                        .short("p")
                        .long("platform")
                        .default_value(default_platform)
                        .possible_values(&["Darwin", "Linux"])
                        .help("Freeze dependencies for this platform"),
                )
                .arg(
                    Arg::with_name("lockfile")
                        .short("l")
                        .long("lockfile")
                        .default_value_if("platform", Some("Darwin"), "deps.Darwin.lock.yml")
                        .default_value_if("platform", Some("Linux"), "deps.Linux.lock.yml")
                        .help("Override the name of the generated lockfile [default: deps.{Platform}.lock.yml]"),
                )
        ).subcommand(
            SubCommand::with_name("create")
                .about("Create an env")
                .arg(
                    Arg::with_name("lockfile")
                        .short("l")
                        .long("lockfile")
                        .help("Create an env from this lockfile"),
                ),
        ).subcommand(
            SubCommand::with_name("checkenv")
                .about("Verify that the env is up to date with the depsfile")
                .arg(
                    Arg::with_name("depfile")
                        .short("d")
                        .long("depfile")
                        .default_value("deps.yml")
                        .help("Compare the env with this depsfile"),
                ),
        ).subcommand(
            SubCommand::with_name("checklocks")
                .about("Verify that the lock files are up to date with the depsfile")
                .arg(
                    Arg::with_name("depfile")
                        .short("d")
                        .long("depfile")
                        .default_value("deps.yml")
                        .help("Check lock files against this depsfile"),
                ).arg(
                    Arg::with_name("lockfiles")
                        .multiple(true)
                        .help("Lockfiles to check.  Defaults to deps.yml.*")
                ),
        )
}

fn main() -> Result<()> {
    let execution_platform = get_platform()?;
    let app_m = get_app(&execution_platform).get_matches();

    let log_level = match app_m.occurrences_of("v") {
        0 => LogLevelFilter::Error,
        1 => LogLevelFilter::Info,
        2 => LogLevelFilter::Debug,
        _ => LogLevelFilter::Debug,
    };
    TermLogger::init(log_level, Config::default())
        .unwrap_or_else(|_| SimpleLogger::init(log_level, Config::default()).unwrap());
    debug!("Setting log level to {}", log_level);

    let val = match app_m.subcommand() {
        ("freeze", Some(sub_m)) => handle_freeze(sub_m),
        ("create", Some(sub_m)) => handle_create(sub_m),
        ("checkenv", Some(sub_m)) => handle_checkenv(sub_m),
        ("checklocks", Some(sub_m)) => handle_checklocks(sub_m),
        _ => Ok(()),
    };
    val
}

fn handle_freeze(matches: &ArgMatches) -> Result<()> {
    info!("Freezing");
    let depfile_path = matches.value_of("depfile").unwrap();

    let execution_platform = get_platform()?;
    let target_platform = matches.value_of("platform").unwrap();

    let lockfile_path = match matches.value_of("lockfile") {
        Some(path) => path.to_string(),
        None => format!("deps.{}.lock.yml", target_platform),
    };
    if execution_platform == target_platform {
        info!("Execution & target platform match");
        return freeze_same_platform(&depfile_path, &lockfile_path);
    }

    match (execution_platform.as_str(), target_platform) {
        ("Darwin", "Linux") => freeze_linux_on_mac(&depfile_path, &lockfile_path),
        _ => {
            let msg = format!(
                "Unable to target {} from {}",
                target_platform, execution_platform
            );
            Err(ioError::new(ioErrorKind::Other, msg).into())
        }
    }
}

fn lockfile_is_up_to_date(lockfile_path: &str, env_hash: &str) -> bool {
    if let Ok(lockfile) = File::open(lockfile_path) {
        if let Ok(found_hash) = read_sigil_hash(lockfile) {
            info!("Found existing lockfile");
            if found_hash == env_hash {
                return true;
            }
        }
    }
    return false;
}

fn run_command(executable: &str, args: &[&str]) -> ioResult<Output> {
    info!("{}, {:?}", executable, args);
    match Command::new(executable).args(args).output() {
        Ok(output) => {
            info!("Command status: {}", output.status);
            if output.status.success() {
                Ok(output)
            } else {
                error!("Error executing: {}, {:?}", executable, args);
                error!("Command status: {}", output.status);
                match String::from_utf8(output.stdout) {
                    Ok(txt) => error!("stdout {}",  txt),
                    _ => {}
                };
                match String::from_utf8(output.stderr) {
                    Ok(txt) => error!("stderr {}",  txt),
                    _ => {}
                };
                Err(ioError::new(ioErrorKind::Other, "Exeuction failed").into())
            }
        }
        Err(err) => {
            info!("error running command {}", err.to_string());
            Err(err)
        }
    }
}

fn freeze_same_platform(depfile_path: &str, lockfile_path: &str) -> Result<()> {
    debug!("Freezing");
    let (env_name, env_hash) = read_env_name_and_hash(&depfile_path)?;

    if lockfile_is_up_to_date(&lockfile_path, &env_hash) {
        info!("Existing lockfile has correct hash. Stopping.");
        return Ok(());
    }

    let conda_path = find_conda()?;
    // Create the environment, but use a name that is unlikely to clobber anything pre-existing.
    let tmp_name = "___conda_lockfile_temp".to_string();
    run_command(
        &conda_path,
        &[
            "env",
            "create",
            "-f",
            &depfile_path,
            "-n",
            &tmp_name,
            "--yes",
        ],
    )?;
    info!("Made new env new env");

    // Read the env create by `conda create`.
    debug!("Reading env");
    let output = run_command(&conda_path, &["env", "export", "-n", &tmp_name])?;
    let lock_data = str::from_utf8(&output.stdout)?;
    debug!("Env data:\n{}", lock_data);

    // Replace the temporary env name with the real one.
    // Also drop the prefix field.  It is irrelevant.
    let mut docs = YamlLoader::load_from_str(lock_data)?;
    let doc = docs.remove(0);
    let mut data_hash = doc.into_hash().unwrap();
    data_hash.insert(Yaml::from_str("name"), Yaml::from_str(&env_name));
    data_hash.remove(&Yaml::from_str("prefix"));
    let lock_spec = Yaml::Hash(data_hash);

    info!("Writing to {}", lockfile_path);
    let lockfile = File::create(lockfile_path)?;
    write_lockfile(lockfile, &lock_spec, &env_hash)?;
    Ok(())
}

fn write_lockfile<W: Write>(mut lockfile: W, lock_spec: &Yaml, env_hash: &str) -> Result<()> {
    info!("Writing lockfile");
    let mut serialized_data = String::new();
    {
        let mut emitter = YamlEmitter::new(&mut serialized_data);
        emitter.dump(&lock_spec)?;
    }

    let env_hash_line = format!("{} {}\n", SIGIL, env_hash);
    lockfile.write_all(env_hash_line.as_bytes())?;
    lockfile.write_all(serialized_data.as_bytes())?;
    info!("Successfully wrote");
    Ok(())
}

fn read_env_name_and_hash(depfile_path: &str) -> Result<(String, String)> {
    let depfile = File::open(&depfile_path)?;
    let env_hash = compute_file_hash(depfile)?;

    let depfile2 = File::open(depfile_path)?;
    let env_spec = read_conda_yaml_data(depfile2)?;
    let env_name = env_spec["name"].as_str().unwrap();
    Ok((env_name.to_string(), env_hash))
}

fn freeze_linux_on_mac(depfile_path: &str, lockfile_path: &str) -> Result<()> {
    info!("Freezing Linux on mac");
    let (env_name, env_hash) = read_env_name_and_hash(&depfile_path)?;

    if lockfile_is_up_to_date(&lockfile_path, &env_hash) {
        info!("Existing lockfile has correct hash. Stopping.");
        return Ok(());
    }

    // The only way to know what should be in an environment is to build it and document what
    // dependencies showed up.  We do this in a docker container to ensure isolation, and to allow
    // us to build lockfiles on mac.
    let img_name = build_container();
    info!("Make container {}", img_name);
    let tmpdir = tempdir_in("/tmp/")?;
    let tmpdir_path = tmpdir.path();

    // put depfile into tmpdir
    {
        info!("Copying depsfile");
        let dest = tmpdir_path.join("deps.yml");
        copy(depfile_path, dest)?;
        let mut envname_file = File::create(tmpdir_path.join("env_name"))?;
        envname_file.write_all(env_name.as_bytes())?;
    }

    // run container
    info!("Running container {}", img_name);
    run_container(&tmpdir_path, &img_name)?;
    info!("Container completed");

    let mut depsfile_data = String::new();
    {
        debug!("reading lockfile");
        let dest = tmpdir_path.join("deps.lock.yml");
        let mut depsfile = File::open(dest)?;
        depsfile.read_to_string(&mut depsfile_data)?;
    }

    // Read the generated lockfile.
    let mut tmp_lockfile = File::open(tmpdir_path.join("deps.lock.yml"))?;
    let mut tmp_lockfile_data = String::new();
    tmp_lockfile.read_to_string(&mut tmp_lockfile_data)?;

    // Validation
    if !lockfile_is_valid(&depsfile_data, &tmp_lockfile_data) {
        return Err(ioError::new(ioErrorKind::Other, "Invalid lockfile").into());
    }

    // Write valid lockfile & include hash
    info!("Writing lockfile {}", lockfile_path);
    {
        let mut lockfile = File::create(lockfile_path)?;
        let env_hash_line = format!("{} {}\n", SIGIL, env_hash);
        lockfile.write_all(env_hash_line.as_bytes())?;
        lockfile.write_all(tmp_lockfile_data.as_bytes())?;
    }
    Ok(())
}

fn build_container() -> String {
    info!("Building container");
    let image_name = "lock_file_maker".to_string();
    let dockerfile = interpolate_dockerfile();
    let mut docker_build = Command::new("docker")
        .args(&["build", "-t", &image_name, "-"])
        .stdin(Stdio::piped())
        .spawn()
        .unwrap();

    let _ = docker_build
        .stdin
        .take()
        .unwrap()
        .write_all(dockerfile.as_bytes());
    docker_build.wait().unwrap();
    image_name
}

fn run_container(dir: &Path, img_name: &str) -> Result<()> {
    let vol_mount = format!("{}:/app/artifacts", dir.to_str().unwrap());
    let output = run_command("docker", &["run", "-v", &vol_mount, "-t", img_name])?;
    let msg = std::str::from_utf8(&(output.stdout))?;
    debug!("{}", msg);
    Ok(())
}

fn lockfile_is_valid(depsfile_data: &str, lockfile_data: &str) -> bool {
    let deps_docs = YamlLoader::load_from_str(depsfile_data).unwrap();
    let deps_yaml = &deps_docs[0];
    let (requested_conda, requested_pip) = get_deps(&deps_yaml);

    let lock_docs = YamlLoader::load_from_str(lockfile_data).unwrap();
    let lock_yaml = &lock_docs[0];
    let (found_conda, found_pip) = get_deps(&lock_yaml);

    // Should probaby do some error reporting if this fails.
    found_conda.is_superset(&requested_conda) && found_pip.is_superset(&requested_pip)
}

fn get_deps(doc: &Yaml) -> (HashSet<&str>, HashSet<&str>) {
    let mut pip_deps = HashSet::new();
    let mut conda_deps = HashSet::new();
    let deps = doc["dependencies"].as_vec().unwrap();
    for d in deps.iter() {
        match d.as_str() {
            Some(conda_dep) => {
                conda_deps.insert(conda_dep);
                continue;
            }
            None => {}
        };
        match d.as_vec() {
            Some(pips) => {
                pip_deps.extend(pips.iter().filter_map(|pip| pip.as_str()));
                continue;
            }
            None => {}
        };
    }
    let conda_deps = only_pkg_names(conda_deps);
    let pip_deps = only_pkg_names(pip_deps);

    (conda_deps, pip_deps)
}

// TODO: make this iterable
fn only_pkg_names(deps: HashSet<&str>) -> HashSet<&str> {
    deps.iter()
        .filter_map(|dep| dep.split("=").nth(0))
        .collect()
}

fn conda_prefix(name: &str) -> Result<PathBuf> {
    let root = env::var("CONDA_ROOT")?;
    let path: PathBuf = [&root, "envs", name].iter().collect();
    Ok(path)
}

fn get_platform() -> Result<String> {
    if cfg!(target_os = "linux") {
        Ok("Linux".to_string())
    } else if cfg!(target_os = "macos") {
        Ok("Darwin".to_string())
    } else {
        Err(ioError::new(ioErrorKind::Other, "Unknown platform").into())
    }
}

fn find_conda() -> Result<String> {
    match env::var("CONDA_EXE") {
        Ok(conda) => Ok(conda),
        Err(_) => match env::var("_CONDA_EXE") {
            Ok(conda) => Ok(conda),
            Err(_) => Err(ioError::new(ioErrorKind::Other, "Unable to find conda").into()),
        },
    }
}

fn handle_create(matches: &ArgMatches) -> Result<()> {
    if cfg!(target_os = "windows") {
        return Err(ioError::new(ioErrorKind::Other, "Unsupported os").into());
    }

    let lockfile_path = match matches.value_of("lockfile") {
        Some(path) => path.to_string(),
        None => match get_platform() {
            Ok(platform) => format!("deps.{}.lock.yml", platform),
            Err(_) => "".to_string(),
        },
    };
    let lockfile = File::open(&lockfile_path)?;
    let doc = read_conda_yaml_data(lockfile)?;
    let env_name = doc["name"].as_str().unwrap();

    let conda_path = find_conda()?;
    info!("conda_path {}", conda_path);
    let output = run_command(
        &conda_path,
        &[
            "env",
            "create",
            "--yes",
            "-q",
            "--json",
            "--name",
            &env_name,
            "-f",
            &lockfile_path.clone(),
        ],
    )?;
    debug!("{:?}", output);

    // Copy lockfile to constructed env
    let mut embeded_lockfile = conda_prefix(&env_name)?;
    embeded_lockfile.push("deps.lock.yml");
    let res = copy(&lockfile_path, embeded_lockfile);
    match res {
        Ok(status) => status,
        Err(_) => {
            let msg = format!("Unable to copy {} to ", lockfile_path);
            return Err(ioError::new(ioErrorKind::Other, msg).into());
        }
    };
    Ok(())
}

fn read_sigil_hash<R: Read>(mut f: R) -> Result<String> {
    let mut file_data = String::new();
    f.read_to_string(&mut file_data)?;
    let hash = file_data
        .lines()
        .filter_map(|line| {
            if line.starts_with(SIGIL) {
                Some(&line[10..])
            } else {
                None
            }
        }).map(|line| line.trim())
        .nth(0);
    match hash {
        Some(hash) => Ok(hash.to_string()),
        None => Err(ioError::new(ioErrorKind::Other, "No Hashes in file").into()),
    }
}

fn compute_file_hash<R: Read>(mut f: R) -> Result<String> {
    let mut depfile_data = String::new();
    f.read_to_string(&mut depfile_data)?;

    // Hash the contents of the file
    let mut m = sha1::Sha1::new();
    m.update(depfile_data.as_bytes());
    Ok(m.digest().to_string())
}

fn read_conda_yaml_data<R: Read>(mut f: R) -> Result<Yaml> {
    let mut depfile_data = String::new();
    f.read_to_string(&mut depfile_data)?;
    let mut docs = YamlLoader::load_from_str(&depfile_data).unwrap();
    let doc = docs.remove(0); // YamlLoader loads multiple documents.  We only want the first.
    Ok(doc)
}

fn handle_checkenv(matches: &ArgMatches) -> Result<()> {
    // Get the data from the depfile.
    let depfile_path = matches.value_of("depfile").unwrap();
    let depfile = File::open(depfile_path)?;
    let expected_hash = compute_file_hash(depfile)?;

    // Extract the name of the environment
    let depfile2 = File::open(depfile_path)?;
    let doc = read_conda_yaml_data(depfile2)?;
    let env_name = doc["name"].as_str().unwrap();
    info!("env name: {}", env_name);

    let root = env::var("CONDA_ROOT").unwrap();
    let lockfile_path: PathBuf = [&root, "envs", env_name, "deps.lock.yml"].iter().collect();
    info!("lockfile_path: {}", lockfile_path.to_str().unwrap());

    let lockfile = File::open(lockfile_path)?;
    let found_hash = read_sigil_hash(lockfile)?;

    if found_hash == expected_hash {
        Ok(())
    } else {
        error!(
            "Hashes do not match (expected, found): {} {}",
            expected_hash, found_hash
        );
        Err(ioError::new(ioErrorKind::Other, "Hashes do not match").into())
    }
}

fn find_lockfiles() -> Vec<PathBuf> {
    let glob_paths: Vec<PathBuf> = glob("deps.*.lock.yml")
        .expect("Failed to read glob pattern")
        .map(|x| x.unwrap())
        .collect();
    glob_paths
}

fn handle_checklocks(matches: &ArgMatches) -> Result<()> {
    let depfile_path = matches.value_of("depfile").unwrap();
    let depfile = File::open(depfile_path)?;
    let expected_hash = compute_file_hash(depfile)?;

    let lockfiles = match matches.values_of("lockfiles") {
        Some(files) => files.map(|p| PathBuf::from(p)).collect(),
        None => find_lockfiles(),
    };

    let mut success = true;
    for lockfile_path in lockfiles {
        let lockfile = File::open(&lockfile_path)?;
        let found_hash = read_sigil_hash(lockfile)?;
        if found_hash != expected_hash {
            success = false;
            error!(
                "Hashes do not match {:?}, {:?}",
                depfile_path, lockfile_path
            );
            error!("lock    hash: {}", found_hash);
            error!("depfile hash: {}", expected_hash);
        }
    }

    if success {
        Ok(())
    } else {
        Err(ioError::new(ioErrorKind::Other, "Hashes do not match").into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_command_success() {
        let result = run_command("ls", &["."]);
        assert!(result.is_ok());
    }

    #[test]
    fn run_command_failure() {
        let result = run_command("cat", &["does-not-exist"]);
        assert!(result.is_err());
    }

    #[test]
    fn freeze_defaults() {
        let execution_platform = get_platform().unwrap();
        let app = get_app(&execution_platform);
        let matches = app.get_matches_from(["conda-lockfile", "freeze"].iter());
        let (name, sub_matches) = matches.subcommand();
        let sub_matches = sub_matches.unwrap();
        assert_eq!(name, "freeze");
        assert_eq!(sub_matches.value_of("depfile").unwrap(), "deps.yml");
        assert_eq!(
            sub_matches.value_of("lockfile").unwrap(),
            format!("deps.{}.lock.yml", execution_platform),
        );
        assert_eq!(
            sub_matches.value_of("platform").unwrap(),
            execution_platform
        );
    }

    #[test]
    fn freeze_options() {
        let execution_platform = get_platform().unwrap();
        let app = get_app(&execution_platform);
        let matches = app.get_matches_from(
            [
                "conda-lockfile",
                "freeze",
                "--depfile",
                "custom_depfile",
                "--lockfile",
                "custom_lockfile",
                "--platform",
                "Linux",
            ]
                .iter(),
        );
        let (name, sub_matches) = matches.subcommand();
        let sub_matches = sub_matches.unwrap();
        assert_eq!(name, "freeze");
        assert_eq!(sub_matches.value_of("depfile").unwrap(), "custom_depfile");
        assert_eq!(sub_matches.value_of("lockfile").unwrap(), "custom_lockfile");
        assert_eq!(sub_matches.value_of("platform").unwrap(), "Linux");
    }

    #[test]
    fn freeze_platform_lockfile() {
        // Make sure setting the platform changes the default lockfile
        let execution_platform = get_platform().unwrap();

        let app = get_app(&execution_platform);
        let matches =
            app.get_matches_from(["conda-lockfile", "freeze", "--platform", "Linux"].iter());
        let (name, sub_matches) = matches.subcommand();
        let sub_matches = sub_matches.unwrap();
        assert_eq!(name, "freeze");
        assert_eq!(sub_matches.value_of("platform").unwrap(), "Linux");
        assert_eq!(
            sub_matches.value_of("lockfile").unwrap(),
            "deps.Linux.lock.yml"
        );

        let app = get_app(&execution_platform);
        let matches =
            app.get_matches_from(["conda-lockfile", "freeze", "--platform", "Darwin"].iter());
        let (name, sub_matches) = matches.subcommand();
        let sub_matches = sub_matches.unwrap();
        assert_eq!(name, "freeze");
        assert_eq!(sub_matches.value_of("platform").unwrap(), "Darwin");
        assert_eq!(
            sub_matches.value_of("lockfile").unwrap(),
            "deps.Darwin.lock.yml"
        );
    }

    #[test]
    fn checklogs_files() {
        let execution_platform = get_platform().unwrap();
        let app = get_app(&execution_platform);
        let matches = app.get_matches_from(["conda-lockfile", "checklocks", "foo", "bar"].iter());
        let (name, sub_matches) = matches.subcommand();
        let sub_matches = sub_matches.unwrap();
        assert_eq!(name, "checklocks");
        assert_eq!(sub_matches.value_of("depfile").unwrap(), "deps.yml");
        let dep_files: Vec<&str> = sub_matches.values_of("lockfiles").unwrap().collect();
        assert_eq!(dep_files, ["foo", "bar"]);
    }
}
