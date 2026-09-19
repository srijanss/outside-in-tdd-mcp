#[cfg(test)]
mod tests {
    #[test]
    fn passing() {
        assert_eq!(2 + 2, 4);
    }

    #[test]
    fn failing() {
        assert_eq!(2 + 2, 5);
    }
}
